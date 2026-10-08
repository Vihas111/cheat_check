"""Local web UI (plan.md §12). Run: python -m checker.cli serve"""

import csv
import io
import re
import shutil
import tempfile
from collections import Counter, defaultdict
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import delete, func, select

from checker.app.worker import Worker
from checker.config import PIPELINE_VERSION, get_settings, save_overrides
from checker.core import verify
from checker.core.cluster import clusters
from checker.core.db import (
    Assignment,
    Base,
    Flag,
    Grade,
    Item,
    Job,
    Mark,
    Match,
    Review,
    Shingle,
    Student,
    Submission,
    Whitelist,
    init_db,
    session_scope,
)
from checker.core.ingest import add_boilerplate, get_assignment, load_roster, register
from checker.core.score import FLAG_HELP

HERE = Path(__file__).parent
worker: Worker | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global worker
    init_db()
    worker = Worker()
    worker.start()
    yield
    worker.stop.set()


app = FastAPI(title="Submission similarity checker", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")

# The React front end (checker/frontend, built with `npm run build` into static/spa) takes over the page URLs when
# it has been built; ?legacy=1 still shows the server-rendered pages, which also remain when it has not.
SPA = HERE / "static" / "spa"
PAGE_URL = re.compile(r"^/(?:new|settings|a/\d+(?:/(?:setup|clusters|calibrate))?|s/\d+|m/\d+|i/\d+)?$")
if (SPA / "_expo").is_dir():
    app.mount("/_expo", StaticFiles(directory=SPA / "_expo"), name="spa-assets")


@app.middleware("http")
async def serve_spa(request: Request, call_next):
    legacy = request.query_params.get("legacy")
    if request.method == "GET" and PAGE_URL.match(request.url.path) and not legacy and (SPA / "index.html").is_file():
        return FileResponse(SPA / "index.html", headers={"Cache-Control": "no-cache"})
    return await call_next(request)

templates = Jinja2Templates(directory=HERE / "templates")
# plain names for the signal chips; FLAG_HELP holds the full explanation
FLAG_LABEL = {
    "HIGH_SINGLE_SOURCE": "Mostly from one file", "HIGH_COLLAGE": "Pieced from many files",
    "FOREIGN_IDENTITY": "Another student's name", "SHARED_IDENTITY": "Shared username",
    "SHARED_RARE_CONTENT": "Shares rare content", "TIMESTAMP_ANOMALY": "Odd timestamp",
    "IDENTICAL_ANNOTATIONS": "Identical crop", "METADATA": "Similar file details",
    "EVASION_HIDDEN_TEXT": "Hidden text", "EVASION_ZERO_WIDTH": "Invisible characters",
    "EVASION_HOMOGLYPH": "Look-alike letters", "EVASION_TRANSFORM": "Flipped or rotated copy",
}
templates.env.globals.update(FLAG_HELP=FLAG_HELP, FLAG_LABEL=FLAG_LABEL, pipeline_version=PIPELINE_VERSION)
# Cache-busts /static links so a changed stylesheet or script is picked up without a hard refresh.
templates.env.globals["asset_version"] = int(max(f.stat().st_mtime for f in (HERE / "static").iterdir()))
templates.env.filters["pct"] = lambda v: "–" if v is None else f"{v:.0%}"
# thumb_path is "images/ab/<sha>.png" relative to data_dir, possibly with Windows separators
templates.env.filters["img"] = lambda p: "/img/" + str(p).replace("\\", "/").removeprefix("images/")


@app.get("/img/{path:path}")
def image(path: str):
    root = (get_settings().data_dir / "images").resolve()
    p = (root / path).resolve()
    if not p.is_relative_to(root) or not p.is_file():
        raise HTTPException(404)
    return Response(p.read_bytes(), media_type="image/png", headers={"Cache-Control": "max-age=86400"})


GRADABLE = (Submission.is_seed.is_(False), Submission.is_reference.is_(False))


def render(request: Request, name: str, **ctx):
    with session_scope() as db:
        ctx.setdefault("assignments", db.scalars(select(Assignment).order_by(Assignment.id)).all())
    return templates.TemplateResponse(request, name, ctx)


# ---------------- grading ----------------

def rubric(a: Assignment) -> list[dict]:
    return a.rubric_json or [{"name": "Score", "points": a.max_score}]


def parse_rubric(text: str) -> list[dict] | None:
    """One criterion per line, "Name | points". Raises ValueError on a bad line."""
    out = []
    for line in text.splitlines():
        if not line.strip():
            continue
        name, sep, pts = line.rpartition("|")
        if not sep or not name.strip() or float(pts) <= 0:
            raise ValueError(line)
        out.append({"name": name.strip(), "points": float(pts)})
    if len({c["name"] for c in out}) != len(out):
        raise ValueError("duplicate criterion name")
    return out or None


def fmt_points(v) -> str:
    return "" if v is None else f"{v:g}"


templates.env.filters["pts"] = fmt_points
GRADE_LABEL = {None: "Not graded", "draft": "Draft", "released": "Released"}
templates.env.globals.update(GRADE_LABEL=GRADE_LABEL)


def latest_reviews(db, sub_ids) -> dict[int, Review]:
    out = {}
    for r in db.scalars(select(Review).where(Review.submission_id.in_(sub_ids)).order_by(Review.ts)):
        out[r.submission_id] = r
    return out


# ---------------- assignments / dashboard ----------------

def assignment_cards(db) -> list[dict]:
    cards = []
    for a in db.scalars(select(Assignment).order_by(Assignment.id.desc())):
        rows = [r for r in dashboard_rows(db, a.id) if r["gradable"]]
        cards.append({"a": a, "total": len(rows),
                      "released": sum(1 for r in rows if r["mark"] and r["mark"].status == "released"),
                      "waiting": sum(1 for r in rows if r["verify"] in ("awaiting", "recheck"))})
    return cards


@app.get("/", response_class=HTMLResponse)
def home(request: Request, msg: str = ""):
    with session_scope() as db:
        cards = assignment_cards(db)
        if not cards:
            return render(request, "welcome.html", msg=msg)
        return render(request, "home.html", cards=cards, msg=msg)


@app.get("/new", response_class=HTMLResponse)
def new_assignment(request: Request):
    return render(request, "welcome.html")


def _dt(v: str | None):
    return datetime.fromisoformat(v) if v else None


@app.post("/assignments")
def create_assignment(name: str = Form(...), start_at: str = Form(""), deadline_at: str = Form(""),
                      rubric_text: str = Form("")):
    aid, crit = make_assignment(name, start_at, deadline_at, rubric_text)
    bad = "?msg=Assignment+created.+Could+not+read+the+rubric;+fix+it+in+Assignment+setup." if crit is False else ""
    return RedirectResponse(f"/a/{aid}{bad}", 303)


def make_assignment(name: str, start_at: str, deadline_at: str, rubric_text: str) -> tuple[int, list[dict] | None | bool]:
    """Returns (id, rubric); rubric is False when its text could not be read (the assignment is still created)."""
    name = name.strip()
    if not name:
        raise HTTPException(400, "Name required")
    try:
        crit = parse_rubric(rubric_text)
    except ValueError:
        crit = False
    with session_scope() as db:
        a = get_assignment(db, name)
        a.start_at, a.deadline_at = _dt(start_at) or a.start_at, _dt(deadline_at) or a.deadline_at
        if crit:
            a.rubric_json, a.max_score = crit, sum(c["points"] for c in crit)
        aid = a.id
    return aid, crit


@app.post("/a/{aid}/edit")
def edit_assignment(aid: int, start_at: str = Form(""), deadline_at: str = Form(""), notes: str = Form(""),
                    rubric_text: str = Form(""), max_score: float = Form(100), name: str = Form("")):
    err = update_assignment(aid, name, start_at, deadline_at, notes, rubric_text, max_score)
    return RedirectResponse(f"/a/{aid}/setup?msg=" + (err or "Saved.").replace(" ", "+"), 303)


def update_assignment(aid: int, name: str, start_at: str, deadline_at: str, notes: str, rubric_text: str,
                      max_score: float) -> str | None:
    """Saves the setup form. Returns an error message, or None when saved."""
    try:
        crit = parse_rubric(rubric_text)
    except ValueError:
        return "Could not read the rubric. Write one part per line, like Part A | 10"
    name = name.strip()
    with session_scope() as db:
        a = db.get(Assignment, aid)
        if name and name != a.name:
            if db.scalar(select(Assignment).where(Assignment.name == name)):
                return "Another assignment already has that name."
            rename_assignment(db, a, name)
        a.start_at, a.deadline_at, a.notes = _dt(start_at), _dt(deadline_at), notes or None
        a.rubric_json, a.max_score = crit, sum(c["points"] for c in crit) if crit else max(max_score, 1)
    return None


def rename_assignment(db, a: Assignment, name: str):
    """Ignored content and the inbox folder are keyed by name, so they move with it."""
    for w in db.scalars(select(Whitelist).where(Whitelist.scope == a.name)):
        w.scope = name
    inbox = get_settings().inbox
    if (inbox / a.name).is_dir() and not (inbox / name).exists():
        (inbox / a.name).rename(inbox / name)
    a.name = name


@app.get("/a/{aid}/setup", response_class=HTMLResponse)
def setup(request: Request, aid: int, msg: str = ""):
    with session_scope() as db:
        a = db.get(Assignment, aid)
        if not a:
            raise HTTPException(404)
        wl_count = db.scalar(select(func.count()).select_from(Whitelist).where(Whitelist.scope == a.name))
        compared = Counter("seed" if s.is_seed else "reference" for s in db.scalars(
            select(Submission).where(Submission.assignment_id == aid, Submission.is_seed
                                     | Submission.is_reference)))
        return render(request, "setup.html", a=a, msg=msg, wl_count=wl_count, compared=compared,
                      rubric_text="\n".join(f"{c['name']} | {c['points']:g}" for c in a.rubric_json or []))


TIER_ORDER = {"HIGH": 0, "MEDIUM": 1, "LOW": 2, "SEED": 3, "REF": 4, None: 5}
# The app only suggests. These are the words the UI uses for its suggestions and for the reviewer's decisions.
TIER_LABEL = {"HIGH": "Strong overlap", "MEDIUM": "Some overlap", "LOW": "Little overlap", "SEED": "Past cohort",
              "REF": "Reference"}
DECISIONS = {"reviewed": "Checked, no action", "false_positive": "Wrong match", "confirmed": "Needs follow-up"}
VERIFY_LABEL = {"awaiting": "Awaiting your decision", "recheck": "New evidence, check again",
                "decided": "Decided", "not_needed": "Nothing flagged"}
templates.env.globals.update(TIER_LABEL=TIER_LABEL, DECISIONS=DECISIONS, VERIFY_LABEL=VERIFY_LABEL)


def suggestion(sub: Submission, flags) -> dict:
    return {"tier": (sub.report_json or {}).get("tier"), "flags": sorted({f.type for f in flags})}


def verification(sub: Submission, flags, review: Review | None) -> str:
    """awaiting | recheck | decided | not_needed. Only a person closes a flagged submission; if the
    suggestion gets stronger after their decision (higher tier, new flag), it goes back to them."""
    cur = suggestion(sub, flags)
    flagged = cur["tier"] in ("HIGH", "MEDIUM") or bool(cur["flags"])
    if review and review.status in DECISIONS:
        seen = review.suggestion_json or {}
        stronger = (TIER_ORDER.get(cur["tier"], 5) < TIER_ORDER.get(seen.get("tier"), 5)
                    or set(cur["flags"]) - set(seen.get("flags", [])))
        return "recheck" if flagged and stronger else "decided"
    return "awaiting" if flagged else "not_needed"


def dashboard_rows(db, aid: int, tier: str = "", status: str = "", q: str = "", grade: str = "", flagged: str = ""):
    subs = db.scalars(select(Submission).where(Submission.assignment_id == aid)).all()
    reviews = latest_reviews(db, [s.id for s in subs])
    marks = {m.submission_id: m for m in db.scalars(select(Mark).where(Mark.submission_id.in_([s.id for s in subs])))}
    flags = defaultdict(list)
    for f in db.scalars(select(Flag).where(Flag.submission_id.in_([s.id for s in subs]))):
        flags[f.submission_id].append(f)
    jobs = {j.submission_id: j for j in db.scalars(select(Job).where(Job.submission_id.in_([s.id for s in subs])))}
    rows = []
    for s in subs:
        r = s.report_json or {}
        rv = reviews.get(s.id)
        row = {"sub": s, "student": s.student, "tier": r.get("tier"), "coverage": r.get("coverage"),
               "num_sources": r.get("num_sources", 0), "top": (r.get("by_source") or [None])[0],
               "flags": sorted(flags[s.id], key=lambda f: {"high": 0, "medium": 1}.get(f.severity, 2)),
               "review": rv, "job": jobs.get(s.id), "mark": marks.get(s.id),
               "gradable": not (s.is_seed or s.is_reference)}
        row["verify"] = verification(s, flags[s.id], rv) if s.status == "done" else None
        if tier and row["tier"] != tier:
            continue
        if status == "awaiting" and row["verify"] not in ("awaiting", "recheck"):
            continue
        if flagged in ("yes", "no"):  # independent of the integrity state: has the check suggested anything?
            if row["verify"] is None or (row["tier"] in ("HIGH", "MEDIUM") or bool(row["flags"])) != (flagged == "yes"):
                continue
        if status in (*DECISIONS, "decided") and row["verify"] != "decided":
            continue
        if grade and (not row["gradable"] or (row["mark"].status if row["mark"] else "none") != grade):
            continue
        if q and q.lower() not in (s.filename + " " + (s.student.name or "" if s.student else "")).lower():
            continue
        rows.append(row)
    if status in DECISIONS:
        rows = [r for r in rows if r["review"].status == status]
    if status == "awaiting":  # checking integrity: strongest suggestion first
        rows.sort(key=lambda r: (TIER_ORDER.get(r["tier"], 5), -(r["coverage"] or 0), r["sub"].filename))
    else:  # grading: class-list order, past cohorts and references last
        rows.sort(key=lambda r: (not r["gradable"], r["sub"].filename.lower()))
    return rows


def job_counts(db, aid: int) -> dict:
    counts = dict(db.execute(select(Job.state, func.count()).join(Submission, Submission.id == Job.submission_id)
                             .where(Submission.assignment_id == aid).group_by(Job.state)).all())
    return {k: counts.get(k, 0) for k in ("queued", "processing", "done", "failed")}


@app.get("/a/{aid}", response_class=HTMLResponse)
def dashboard(request: Request, aid: int, tier: str = "", status: str = "", q: str = "", msg: str = "",
              partial: int = 0, grade: str = ""):
    with session_scope() as db:
        a = db.get(Assignment, aid)
        if not a:
            raise HTTPException(404)
        rows = dashboard_rows(db, aid, tier, status, q, grade)
        everyone = rows if not (tier or status or q or grade) else dashboard_rows(db, aid)
        verify = Counter(r["verify"] for r in everyone)
        grades = Counter(r["mark"].status if r["mark"] else "none" for r in everyone if r["gradable"])
        counts = job_counts(db, aid)
        tiers = Counter((s.report_json or {}).get("tier") for s in
                        db.scalars(select(Submission).where(Submission.assignment_id == aid)))
        failed = db.execute(select(Submission.filename, Job.error).join(Job, Job.submission_id == Submission.id)
                            .where(Submission.assignment_id == aid, Job.state == "failed")).all()
        wl_count = db.scalar(select(func.count()).select_from(Whitelist).where(Whitelist.scope == a.name))
        has_roster = db.scalar(select(func.count()).select_from(Student).where(Student.name.is_not(None))) > 0
        ctx = dict(a=a, rows=rows, counts=counts, tiers=tiers, failed=failed, tier=tier, status=status, q=q,
                   msg=msg, wl_count=wl_count, has_roster=has_roster, verify=verify, grades=grades, grade=grade,
                   rubric=rubric(a),
                   rubric_text="\n".join(f"{c['name']} | {c['points']:g}" for c in a.rubric_json or []),
                   rescanning=worker is not None and a.name in worker.busy_assignments,
                   inbox=get_settings().inbox / a.name)
        return render(request, "_table.html" if partial else "dashboard.html", **ctx)


@app.get("/api/a/{aid}/status")
def status(aid: int):
    with session_scope() as db:
        a = db.get(Assignment, aid)
        c = job_counts(db, aid)
        # changes whenever any score changes, so the page only refreshes when there is something new
        stamp = db.scalar(select(func.count()).select_from(Match).join(Submission, Submission.id == Match.submission_id)
                          .where(Submission.assignment_id == aid))
    from checker.core import progress
    return JSONResponse({**c, "stamp": f"{c}-{stamp}",
                         "rescanning": worker is not None and a.name in worker.busy_assignments,
                         "rescan": progress.snapshot(a.name)})


@app.post("/a/{aid}/upload")
async def upload(aid: int, files: list[UploadFile] = File(...), mode: str = Form("submission")):
    with session_scope() as db:
        name = db.get(Assignment, aid).name
    added, skipped, errors = [], [], []
    with tempfile.TemporaryDirectory() as tmp:
        for f in files:
            fname = Path(f.filename or "upload.pdf").name
            if not fname.lower().endswith(".pdf"):
                errors.append(f"{fname}: not a PDF")
                continue
            data = await f.read()
            if not data.startswith(b"%PDF"):
                errors.append(f"{fname}: not a valid PDF file")
                continue
            p = Path(tmp) / fname
            p.write_bytes(data)
            _, is_new = register(p, name, seed=mode == "seed", reference=mode == "reference")
            (added if is_new else skipped).append(fname)
    return {"added": added, "skipped": skipped, "errors": errors}


@app.post("/a/{aid}/rescan")
def rescan_route(aid: int):
    with session_scope() as db:
        name = db.get(Assignment, aid).name
    worker.rescan_async(name)
    return RedirectResponse(f"/a/{aid}/setup?msg=Re-scan+started.+Scores+update+when+it+finishes.", 303)


@app.post("/a/{aid}/retry")
def retry_failed(aid: int):
    with session_scope() as db:
        for j in db.scalars(select(Job).join(Submission, Submission.id == Job.submission_id)
                            .where(Submission.assignment_id == aid, Job.state == "failed")):
            j.state = "queued"
    return RedirectResponse(f"/a/{aid}", 303)


@app.post("/a/{aid}/boilerplate")
async def boilerplate(aid: int, files: list[UploadFile] = File(...)):
    with session_scope() as db:
        name = db.get(Assignment, aid).name
    n = 0
    with tempfile.TemporaryDirectory() as tmp:
        for f in files:
            p = Path(tmp) / Path(f.filename or "brief.txt").name
            p.write_bytes(await f.read())
            n += add_boilerplate(p, name)
    worker.rescan_async(name)
    return RedirectResponse(f"/a/{aid}/setup?msg=Brief+added+({n}+fingerprints).+Re-scanning.", 303)


# ---------------- submission detail ----------------

@app.post("/s/{sid}/student")
def set_student(sid: int, student_id: str = Form(...), name: str = Form("")):
    """Tie a submission to a student. Files of the same student are never compared, so the assignment
    is re-scanned."""
    student_id, name = student_id.strip(), name.strip()
    with session_scope() as db:
        sub = db.get(Submission, sid)
        if not sub:
            raise HTTPException(404)
        st = db.scalar(select(Student).where(Student.student_id == student_id)) if student_id else None
        if student_id and not st:
            st = Student(student_id=student_id)
            db.add(st)
            db.flush()
        if st and name:
            st.name = name
        sub.student_pk = st.id if st else None
        aname = sub.assignment.name
    worker.rescan_async(aname)
    return RedirectResponse(f"/s/{sid}?saved_student=1", 303)

def _item_label(it: Item) -> str:
    what = {"image": "image", "page_render": "scanned page", "text_block": "typed answer"}[it.kind]
    return f"page {it.page} {what}" + (f" {it.idx + 1}" if it.kind == "image" else "")


@app.get("/s/{sid}", response_class=HTMLResponse)
def submission(request: Request, sid: int):
    with session_scope() as db:
        sub = db.get(Submission, sid)
        if not sub:
            raise HTTPException(404)
        report = sub.report_json or {}
        items = db.scalars(select(Item).where(Item.submission_id == sid).order_by(Item.page, Item.idx)).all()
        matches = db.scalars(select(Match).where(Match.submission_id == sid)).all()
        others = {s.id: s for s in db.scalars(select(Submission).where(
            Submission.id.in_({m.other_submission_id for m in matches})))}
        other_items = {i.id: i for i in db.scalars(select(Item).where(
            Item.id.in_({m.other_item_id for m in matches})))}
        by_item = defaultdict(list)
        for m in sorted(matches, key=lambda m: -m.score):
            by_item[m.item_id].append(m)
        weights = report.get("item_weights", {})
        dfs = report.get("item_df", {})
        provenance = [{"item": it, "label": _item_label(it), "weight": weights.get(str(it.id)),
                       "df": dfs.get(str(it.id)), "matches": by_item.get(it.id, [])}
                      for it in items if it.is_content]
        flags = sorted(db.scalars(select(Flag).where(Flag.submission_id == sid)).all(),
                       key=lambda f: {"high": 0, "medium": 1, "low": 2}.get(f.severity, 3))
        reviews = db.scalars(select(Review).where(Review.submission_id == sid).order_by(Review.ts.desc())).all()
        top_ids = [b["submission_id"] for b in report.get("by_source", [])[:4]]
        meta_rows = []
        keys = ["producer", "creator", "author", "creationDate", "modDate"]
        for k in keys:
            meta_rows.append([k, (sub.pdf_meta_json or {}).get("info", {}).get(k, "")] +
                             [(others[o].pdf_meta_json or {}).get("info", {}).get(k, "") if o in others else ""
                              for o in top_ids])
        job = db.scalar(select(Job).where(Job.submission_id == sid))
        verify = verification(sub, flags, reviews[0] if reviews else None) if sub.status == "done" else None
        queue = [r["sub"].id for r in dashboard_rows(db, sub.assignment_id, status="awaiting") if r["sub"].id != sid]
        roster = [r for r in dashboard_rows(db, sub.assignment_id) if r["gradable"]]
        ids = [r["sub"].id for r in roster]
        pos = ids.index(sid) if sid in ids else -1
        after = roster[pos + 1:] + roster[:max(pos, 0)]
        ungraded = [r["sub"].id for r in after if not (r["mark"] and r["mark"].status == "released")]
        mark = db.get(Mark, sid)
        return render(request, "submission.html", sub=sub, a=sub.assignment, report=report, provenance=provenance,
                      mark=mark, scores=(mark.scores_json or {}) if mark else {}, rubric=rubric(sub.assignment),
                      pos=pos, count=len(ids), prev_id=ids[pos - 1] if pos > 0 else None,
                      next_sub=ids[pos + 1] if 0 <= pos < len(ids) - 1 else None,
                      next_ungraded=ungraded[0] if ungraded else None,
                      flags=flags, reviews=reviews, others=others, other_items=other_items,
                      meta_rows=meta_rows, meta_heads=[others[o].filename for o in top_ids if o in others],
                      label=_item_label, job=job, student=sub.student,
                      verify=verify, next_id=queue[0] if queue else None)


@app.get("/s/{sid}/pdf")
def submission_pdf(sid: int):
    with session_scope() as db:
        sub = db.get(Submission, sid)
        path = Path(sub.stored_path) if sub and sub.stored_path else None
        name = sub.filename if sub else ""
    if not path or not path.is_file():
        raise HTTPException(404)
    return FileResponse(path, media_type="application/pdf", content_disposition_type="inline", filename=name)


@app.post("/s/{sid}/mark")
async def mark_route(request: Request, sid: int):
    form = await request.form()
    action = str(form.get("action", "save"))
    with session_scope() as db:
        sub = db.get(Submission, sid)
        if not sub:
            raise HTTPException(404)
        raw = {c["name"]: str(form.get(f"score_{i}", "")) for i, c in enumerate(rubric(sub.assignment))}
    err, state = apply_mark(sid, raw, str(form.get("feedback", "")), action)
    if err:
        return RedirectResponse(f"/s/{sid}?err={err.replace(' ', '+')}", 303)
    nxt = str(form.get("next", ""))
    if action == "release_next" and nxt.isdigit():
        return RedirectResponse(f"/s/{nxt}?saved_prev={sid}", 303)
    return RedirectResponse(f"/s/{sid}?saved_mark={'unreleased' if action == 'unrelease' else state}", 303)


def apply_mark(sid: int, raw: dict[str, str], feedback: str, action: str) -> tuple[str | None, str | None]:
    """Save the grader's marks (raw: criterion name -> typed value). Releasing needs every part marked and, for a
    flagged submission, the grader's integrity decision first: a suggestion never slips through unchecked.
    Returns (error, state); a bad number saves nothing, a blocked release still saves the draft."""
    with session_scope() as db:
        sub = db.get(Submission, sid)
        if not sub:
            raise HTTPException(404)
        scores, missing = {}, []
        for c in rubric(sub.assignment):
            typed = str(raw.get(c["name"], "")).strip()
            if not typed:
                missing.append(c["name"])
                continue
            try:
                v = float(typed)
            except ValueError:
                v = -1
            if not 0 <= v <= c["points"]:
                return f"{c['name']}: enter a number from 0 to {c['points']:g}.", None
            scores[c["name"]] = v
        m = db.get(Mark, sid)
        if m is None:
            m = Mark(submission_id=sid)
            db.add(m)
        m.scores_json, m.feedback = scores, feedback.strip() or None
        m.total = sum(scores.values()) if scores else None
        err = None
        if action.startswith("release"):
            flags = db.scalars(select(Flag).where(Flag.submission_id == sid)).all()
            rv = latest_reviews(db, [sid]).get(sid)
            if sub.status in ("queued", "processing"):
                err = "The integrity check is still running. Release the grade when it finishes."
            elif sub.status == "done" and verification(sub, flags, rv) in ("awaiting", "recheck"):
                err = "This submission was flagged. Record your integrity decision before releasing the grade."
            elif missing:
                err = f"Give marks for {', '.join(missing)} before releasing."
        m.status = "released" if action.startswith("release") and not err else "draft"
        return err, m.status


@app.post("/s/{sid}/review")
def review(sid: int, status: str = Form(...), note: str = Form("")):
    if status not in DECISIONS and status != "unreviewed":
        raise HTTPException(400)
    if status == "confirmed" and not note.strip():
        return RedirectResponse(f"/s/{sid}?err=Add+a+note+saying+what+needs+follow-up.", 303)
    with session_scope() as db:
        sub = db.get(Submission, sid)
        flags = db.scalars(select(Flag).where(Flag.submission_id == sid)).all()
        db.add(Review(submission_id=sid, status=status, note=note.strip() or None,
                      suggestion_json=suggestion(sub, flags)))
    return RedirectResponse(f"/s/{sid}?saved={status}", 303)


@app.post("/item/{iid}/ignore")
def ignore_item(iid: int, back: str = Form("/")):
    """Whitelist an image (by pHash) or a passage (its text fingerprints) for this assignment, then re-scan."""
    with session_scope() as db:
        it = db.get(Item, iid)
        a = it.submission.assignment
        reason = f"ignored from {it.submission.filename}, {_item_label(it)}"
        if it.phash:
            db.add(Whitelist(kind="image", fingerprint=it.phash.hex(), scope=a.name, reason=reason))
        for h in db.scalars(select(Shingle.hash).where(Shingle.item_id == iid)).all():
            db.add(Whitelist(kind="shingle", fingerprint=str(h), scope=a.name, reason=reason))
        name = a.name
    worker.rescan_async(name)
    return RedirectResponse(back if back.startswith("/") else "/", 303)


def dismiss_match(mid: int) -> dict | None:
    """Mark the two items of this match as "not a match": the pair stops counting for every kind of match, in
    both directions, now and on every later scan. Returns what is needed to undo it."""
    import json as _json
    with session_scope() as db:
        m = db.get(Match, mid)
        if not m:
            return None
        a, b = db.get(Item, m.item_id), db.get(Item, m.other_item_id)
        sa, sb = db.get(Submission, a.submission_id), db.get(Submission, b.submission_id)
        name = sa.assignment.name
        ka, kb = [a.submission_id, a.page, a.idx], [b.submission_id, b.page, b.idx]
        reason = f"not a match: {sa.filename} {_item_label(a)} and {sb.filename} {_item_label(b)}"
        if not db.scalar(select(Whitelist.id).where(Whitelist.kind == "pair", Whitelist.scope == name,
                                                    Whitelist.reason == reason)):
            db.add(Whitelist(kind="pair", fingerprint=_json.dumps({"a": ka, "b": kb}), scope=name, reason=reason))
        db.execute(delete(Match).where(
            ((Match.item_id == a.id) & (Match.other_item_id == b.id))
            | ((Match.item_id == b.id) & (Match.other_item_id == a.id))))
        out = {"scope": name, "reason": reason, "submission_id": sa.id}
    if worker:
        worker.rescan_async(name)
    return out


def item_lines(it: Item) -> list[str]:
    """The readable lines of an item's text, in the order the front end shows them (indexes are stable)."""
    return [ln.strip() for ln in (it.ocr_text or "").splitlines() if ln.strip()]


def ignore_text(iid: int, indexes: list[int]) -> str | None:
    """Ignore only the chosen lines of an item (for example the question, not the answer) in its assignment.
    Returns the assignment name, or an error message starting with '!'."""
    from checker.core.ingest import text_fingerprints
    from checker.core.normalize import normalize_text
    with session_scope() as db:
        it = db.get(Item, iid)
        if not it:
            return None
        lines = item_lines(it)
        chosen = [lines[i] for i in sorted(set(indexes)) if 0 <= i < len(lines)]
        norm = normalize_text("\n".join(chosen))
        hashes = set().union(*text_fingerprints(norm).values()) if norm else set()
        if not hashes:
            return "!That is too short to recognise. Select at least a few words."
        snippet = " ".join(chosen)
        snippet = snippet[:70] + ("…" if len(snippet) > 70 else "")
        name = it.submission.assignment.name
        reason = f'ignored text "{snippet}"'
        for h in hashes:
            db.add(Whitelist(kind="shingle", fingerprint=str(h), scope=name, reason=reason))
    if worker:
        worker.rescan_async(name)
    return name


# ---------------- comparison viewer ----------------

@app.get("/m/{mid}", response_class=HTMLResponse)
def compare(request: Request, mid: int):
    with session_scope() as db:
        m = db.get(Match, mid)
        if not m:
            raise HTTPException(404)
        a, b = db.get(Item, m.item_id), db.get(Item, m.other_item_id)
        sa, sb = db.get(Submission, m.submission_id), db.get(Submission, m.other_submission_id)
        passages = verify.text_passages(a.norm_text, b.norm_text)
        ha = verify.highlight(a.norm_text, [p["a"] for p in passages])
        hb = verify.highlight(b.norm_text, [p["b"] for p in passages])
        siblings = db.scalars(select(Match).where(Match.submission_id == m.submission_id,
                                                  Match.other_submission_id == m.other_submission_id)
                              .order_by(Match.item_id)).all()
        return render(request, "compare.html", m=m, ia=a, ib=b, sa=sa, sb=sb, ha=ha, hb=hb, passages=passages,
                      label=_item_label, siblings=siblings, a=sa.assignment,
                      both_images=bool(a.thumb_path and b.thumb_path))


@app.get("/m/{mid}/overlay.png")
def overlay(mid: int):
    d = get_settings().data_dir
    with session_scope() as db:
        m = db.get(Match, mid)
        a, b = db.get(Item, m.item_id), db.get(Item, m.other_item_id)
        pa, pb, ma, mb = a.thumb_path, b.thumb_path, a.masks_json, b.masks_json
    if not (pa and pb):
        raise HTTPException(404)
    return Response(verify.orb_overlay_png(d / pa, d / pb, ma, mb), media_type="image/png")


# ---------------- clusters / calibration / export ----------------

@app.get("/a/{aid}/clusters", response_class=HTMLResponse)
def clusters_page(request: Request, aid: int):
    with session_scope() as db:
        cl = clusters(db, aid)
        return render(request, "clusters.html", a=db.get(Assignment, aid), clusters=cl)


def histogram(values: list[float], bins: int = 20, lo: float = 0.0, hi: float = 1.0) -> list[dict]:
    counts = [0] * bins
    for v in values:
        counts[min(bins - 1, max(0, int((v - lo) / (hi - lo) * bins)))] += 1
    top = max(counts) or 1
    return [{"lo": lo + i * (hi - lo) / bins, "n": c, "h": c / top} for i, c in enumerate(counts)]


def outlier_cutoff(values: list[float]) -> float | None:
    """Q3 + 1.5 IQR: the point where outliers separate from the crowd."""
    if len(values) < 8:
        return None
    v = sorted(values)
    q1, q3 = v[len(v) // 4], v[3 * len(v) // 4]
    cut = round(q3 + 1.5 * (q3 - q1), 3)
    return cut if cut < v[-1] else None  # a cut above every value separates nothing (e.g. when copies are the majority)


@app.get("/a/{aid}/calibrate", response_class=HTMLResponse)
def calibrate_page(request: Request, aid: int):
    with session_scope() as db:
        a = db.get(Assignment, aid)
        subs = db.scalars(select(Submission).where(Submission.assignment_id == aid, Submission.status == "done",
                                                   Submission.is_reference.is_(False))).all()
        cov = [(s.report_json or {}).get("coverage", 0) for s in subs]
        top = [((s.report_json or {}).get("by_source") or [{"share": 0}])[0]["share"] for s in subs]
        ms = db.scalars(select(Match).join(Submission, Submission.id == Match.submission_id)
                        .where(Submission.assignment_id == aid)).all()
        dist = [m.detail_json.get("distance", 0) for m in ms if m.kind == "image_hash"]
        cont = [m.score for m in ms if m.kind in ("ocr_text", "code_structure")]
        s = get_settings()
        charts = [
            {"title": "Coverage per submission", "hist": histogram(cov), "cut": outlier_cutoff(cov),
             "current": s.tier_medium_coverage, "setting": "tier_medium_coverage", "fmt": "pct"},
            {"title": "Largest single-source share", "hist": histogram(top), "cut": outlier_cutoff(top),
             "current": s.single_source_high, "setting": "single_source_high", "fmt": "pct"},
            {"title": "Text containment of matched passages", "hist": histogram(cont), "cut": None,
             "current": s.text_containment_min, "setting": "text_containment_min", "fmt": "pct"},
            {"title": "Image hash distance of matched images (bits)",
             "hist": histogram(dist, bins=s.phash_near + 1, lo=0, hi=s.phash_near + 1), "cut": None,
             "current": s.phash_near, "setting": "phash_near", "fmt": "int"},
        ]
        return render(request, "calibrate.html", a=a, charts=charts, n=len(subs))


@app.get("/a/{aid}/export.csv")
def export_csv(aid: int):
    with session_scope() as db:
        a = db.get(Assignment, aid)
        rows = dashboard_rows(db, aid)
        buf = io.StringIO()
        w = csv.writer(buf)
        # the app's columns are suggestions; only reviewer_decision is an outcome, and only a person sets it
        w.writerow(["submission_id", "filename", "student_id", "student_name", "suggested_tier", "coverage",
                    "num_sources", "top_source", "top_source_share", "flags", "verification", "reviewer_decision",
                    "reviewer_note", "decided_at", "reasons", "pipeline_version"])
        for r in rows:
            s, rep = r["sub"], r["sub"].report_json or {}
            w.writerow([s.id, s.filename, r["student"].student_id if r["student"] else "",
                        (r["student"].name or "") if r["student"] else "", r["tier"], r["coverage"],
                        r["num_sources"], (r["top"] or {}).get("filename", ""), (r["top"] or {}).get("share", ""),
                        ";".join(f.type for f in r["flags"]), r["verify"] or s.status,
                        DECISIONS.get(r["review"].status, "") if r["verify"] == "decided" else "",
                        (r["review"].note or "") if r["review"] else "",
                        r["review"].ts.isoformat(timespec="minutes") if r["review"] else "",
                        " | ".join(rep.get("reasons", [])), s.pipeline_version])
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": f'attachment; filename="{a.name}-integrity.csv"'})


@app.get("/a/{aid}/grades.csv")
def export_grades(aid: int):
    with session_scope() as db:
        a = db.get(Assignment, aid)
        crit = rubric(a)
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["student_id", "student_name", "filename", "status", "total", "out_of",
                    *[c["name"] for c in crit], "feedback", "integrity"])
        for r in dashboard_rows(db, aid):
            if not r["gradable"]:
                continue
            s, m, st = r["sub"], r["mark"], r["student"]
            sc = (m.scores_json or {}) if m else {}
            w.writerow([st.student_id if st else "", (st.name or "") if st else "", s.filename,
                        m.status if m else "not graded", fmt_points(m.total) if m else "", fmt_points(a.max_score),
                        *[fmt_points(sc.get(c["name"])) for c in crit], (m.feedback or "") if m else "",
                        DECISIONS.get(r["review"].status, "") if r["verify"] == "decided"
                        else VERIFY_LABEL.get(r["verify"], s.status)])
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": f'attachment; filename="{a.name}-grades.csv"'})


# ---------------- settings ----------------

# setting -> one-line explanation shown on the settings page
EDITABLE = {
    "phash_near": "Max differing bits (of 144) for two images to count as the same screenshot.",
    "phash_exact": "At or below this distance images are treated as identical (no feature check).",
    "text_containment_min": "Share of an item's text that must appear elsewhere to count as a text match.",
    "code_containment_min": "Same, for code structure (identifiers ignored).",
    "min_shared_shingles": "Minimum shared 5-word sequences before text is compared at all.",
    "orb_min_inliers": "Feature points that must line up to confirm a near-duplicate image.",
    "common_fraction": "Content found in more than this share of submissions gets no weight (template material).",
    "single_source_high": "HIGH when this share of a submission's content comes from one other submission.",
    "collage_high": "HIGH when this share of content comes from several sources combined...",
    "collage_min_sources": "...and at least this many different sources contribute.",
    "rare_max_submissions": "Content shared with at most this many others counts as rare.",
    "tier_medium_coverage": "MEDIUM when overall matched coverage is at least this.",
    "min_idf_population": "Rarity weights assume at least this many submissions (keeps early scores stable).",
    "top_n": "How many most-similar submissions are verified and stored per submission.",
    "cluster_min_edge": "Minimum shared weighted content for two submissions to be linked in clusters.",
    "filename_regex": "Regex extracting student_id from the PDF filename.",
    "student_id_regex": "Regex for student IDs found inside screenshots.",
    "ocr_engine": "auto, rapidocr or tesseract (all run locally).",
    "ocr_gpu_id": "Which GPU to use if you have more than one (0, 1, ...). Restart to apply.",
    "ocr_device": "auto, cpu, cuda or directml. Needs the GPU build of onnxruntime; see the README. Restart to apply.",
    "render_dpi": "Page render resolution for scanned / vector pages.",
    "workers": "Parallel ingestion jobs (restart to apply).",
}


@app.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request, msg: str = ""):
    s = get_settings()
    fields = [{"name": k, "value": getattr(s, k), "help": h, "type": type(getattr(s, k)).__name__}
              for k, h in EDITABLE.items()]
    with session_scope() as db:
        roster = db.scalar(select(func.count()).select_from(Student).where(Student.name.is_not(None)))
        wl = db.execute(select(Whitelist.kind, Whitelist.scope, Whitelist.reason, func.count(), func.min(Whitelist.id))
                        .group_by(Whitelist.kind, Whitelist.scope, Whitelist.reason)).all()
    from checker.core.ocr import available_engines
    return render(request, "settings.html", fields=fields, roster=roster, wl=wl, msg=msg,
                  engines=available_engines())


@app.post("/settings")
async def save_settings(request: Request):
    form = await request.form()
    s = get_settings()
    values = {}
    for k in EDITABLE:
        if k in form:
            cur = getattr(s, k)
            raw = str(form[k]).strip()
            try:
                values[k] = type(cur)(raw)
            except ValueError:
                return RedirectResponse(f"/settings?msg=Invalid+value+for+{k}", 303)
    save_overrides(values)
    return RedirectResponse("/settings?msg=Saved.+Use+Re-scan+on+an+assignment+to+apply+new+thresholds.", 303)


@app.post("/settings/roster")
async def roster_upload(file: UploadFile = File(...)):
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "roster.csv"
        p.write_bytes(await file.read())
        try:
            with session_scope() as db:
                n = load_roster(db, p)
        except (UnicodeDecodeError, csv.Error, KeyError):
            return RedirectResponse("/settings?msg=Could+not+read+roster+CSV", 303)
    return RedirectResponse(f"/settings?msg=Roster+loaded:+{n}+students", 303)


@app.post("/settings/erase")
def erase_all(confirm: str = Form("")):
    """Delete every assignment, submission, grade, roster entry and stored file. Settings are kept."""
    if confirm.strip().lower() != "erase":
        return RedirectResponse("/settings?msg=Nothing+was+erased.+Type+erase+to+confirm.", 303)
    # ponytail: a file being read at this moment may fail its job; nothing is left behind to retry
    with session_scope() as db:
        for table in reversed(Base.metadata.sorted_tables):
            db.execute(table.delete())
    root = get_settings().data_dir
    for folder in ("pdfs", "images", "inbox"):
        shutil.rmtree(root / folder, ignore_errors=True)
    return RedirectResponse("/settings?msg=All+data+erased.", 303)


def delete_assignment(aid: int) -> str | None:
    """Delete one assignment with its submissions, grades, decisions and stored files. Other assignments,
    settings and the roster are kept. Returns the assignment name, or None if it does not exist."""
    with session_scope() as db:
        a = db.get(Assignment, aid)
        if not a:
            return None
        name = a.name
        subs = db.scalars(select(Submission).where(Submission.assignment_id == aid)).all()
        sub_ids = [x.id for x in subs]
        shas = {x.sha256 for x in subs}
        thumbs = set(db.scalars(select(Item.thumb_path).where(Item.submission_id.in_(sub_ids))).all())
        student_pks = {x.student_pk for x in subs if x.student_pk}
        for x in subs:  # children go with them (items, shingles, matches, flags, reviews, marks, jobs)
            db.delete(x)
        db.flush()
        db.execute(delete(Grade).where(Grade.assignment_id == aid))
        db.execute(delete(Whitelist).where(Whitelist.scope == name))
        db.delete(a)
        db.flush()
        # files no remaining submission uses
        kept_shas = set(db.scalars(select(Submission.sha256).where(Submission.sha256.in_(shas))).all())
        kept_thumbs = set(db.scalars(select(Item.thumb_path).where(Item.thumb_path.in_(thumbs))).all())
        # students made only from filenames, now without any submission
        for pk in student_pks:
            st = db.get(Student, pk)
            if st and not (st.name or st.username or st.email) and not db.scalar(
                    select(func.count()).select_from(Submission).where(Submission.student_pk == pk)):
                db.delete(st)
    root = get_settings().data_dir
    for sha in shas - kept_shas:
        (root / "pdfs" / f"{sha}.pdf").unlink(missing_ok=True)
    for t in thumbs - kept_thumbs:
        if t:
            (root / t).unlink(missing_ok=True)
    shutil.rmtree(root / "inbox" / name, ignore_errors=True)  # or the watcher would bring the files back
    return name


@app.post("/settings/whitelist/delete")
def whitelist_delete(kind: str = Form(...), reason: str = Form(""), scope: str = Form("")):
    with session_scope() as db:
        q = select(Whitelist).where(Whitelist.kind == kind, Whitelist.reason == (reason or None),
                                    Whitelist.scope == scope if scope else Whitelist.scope.is_(None))
        found = db.scalars(q).all()
        if kind == "region":
            from checker.core import regions
            regions.delete_files(found)
        for w in found:
            db.delete(w)
    if scope and worker:  # take the rule out of the comparison right away
        worker.rescan_async(scope)
    return RedirectResponse("/settings?msg=Removed.+Re-scanning+the+assignment.", 303)


from checker.app import api  # noqa: E402  (JSON API for the React front end; needs the helpers above)

app.include_router(api.router)
