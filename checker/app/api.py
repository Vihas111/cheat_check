"""JSON API for the React front end (checker/frontend). It reuses the helpers in main.py, so the grading,
verification and export rules stay in one place; the old HTML pages keep working beside it."""

import csv
import tempfile
from collections import Counter, defaultdict
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import func, select

from checker.app import main as M
from checker.config import get_settings, save_overrides
from checker.core import verify as V
from checker.core.cluster import clusters
from checker.core.db import (
    Assignment, Flag, Item, Job, Mark, Match, Review, Student, Submission, Whitelist, session_scope,
)
from checker.core.ingest import load_roster
from checker.core.score import FLAG_HELP

router = APIRouter(prefix="/api")


def iso(v):
    return v.isoformat(timespec="minutes") if v else None


def img(p) -> str | None:
    return "/img/" + str(p).replace("\\", "/").removeprefix("images/") if p else None


def student_json(st: Student | None):
    return {"student_id": st.student_id, "name": st.name} if st else None


def assignment_json(a: Assignment) -> dict:
    return {"id": a.id, "name": a.name, "notes": a.notes, "max_score": a.max_score, "start_at": iso(a.start_at),
            "deadline_at": iso(a.deadline_at), "rubric": M.rubric(a), "has_rubric": bool(a.rubric_json),
            "rubric_text": "\n".join(f"{c['name']} | {c['points']:g}" for c in a.rubric_json or [])}


def row_json(r: dict) -> dict:
    s, mk, rv, top = r["sub"], r["mark"], r["review"], r["top"]
    return {"id": s.id, "filename": s.filename, "student": student_json(r["student"]), "gradable": r["gradable"],
            "is_seed": s.is_seed, "is_reference": s.is_reference, "status": r["job"].state if r["job"] else s.status,
            "mark": {"total": mk.total, "status": mk.status} if mk else None, "verify": r["verify"],
            "decision": rv.status if rv and r["verify"] == "decided" else None, "tier": r["tier"],
            "coverage": r["coverage"], "top": {"filename": top["filename"]} if top else None}


def labels() -> dict:
    return {"tier": M.TIER_LABEL, "decision": M.DECISIONS, "verify": M.VERIFY_LABEL, "flag": M.FLAG_LABEL}


# ---------------- assignments ----------------

@router.get("/meta")
def meta():
    return {"labels": labels(), "pipeline_version": M.PIPELINE_VERSION}


@router.get("/assignments")
def assignments():
    with session_scope() as db:
        return [{**assignment_json(c["a"]), "total": c["total"], "released": c["released"], "waiting": c["waiting"]}
                for c in M.assignment_cards(db)]


class NewAssignment(BaseModel):
    name: str
    start_at: str = ""
    deadline_at: str = ""
    rubric_text: str = ""


@router.post("/assignments")
def create_assignment(body: NewAssignment):
    aid, crit = M.make_assignment(body.name, body.start_at, body.deadline_at, body.rubric_text)
    return {"id": aid, "rubric_ok": crit is not False}


@router.get("/a/{aid}")
def assignment(aid: int, tier: str = "", status: str = "", q: str = "", grade: str = ""):
    with session_scope() as db:
        a = db.get(Assignment, aid)
        if not a:
            raise HTTPException(404)
        rows = M.dashboard_rows(db, aid, tier, status, q, grade)
        everyone = rows if not (tier or status or q or grade) else M.dashboard_rows(db, aid)
        failed = db.execute(select(Submission.filename, Job.error).join(Job, Job.submission_id == Submission.id)
                            .where(Submission.assignment_id == aid, Job.state == "failed")).all()
        compared = Counter("seed" if s.is_seed else "reference" for s in db.scalars(
            select(Submission).where(Submission.assignment_id == aid, Submission.is_seed | Submission.is_reference)))
        return {
            "assignment": assignment_json(a), "rows": [row_json(r) for r in rows], "total": len(everyone),
            "counts": M.job_counts(db, aid), "verify": dict(Counter(r["verify"] for r in everyone)),
            "grades": dict(Counter(r["mark"].status if r["mark"] else "none" for r in everyone if r["gradable"])),
            "failed": [{"filename": f, "error": (e or "unknown error")[:300]} for f, e in failed],
            "wl_count": db.scalar(select(func.count()).select_from(Whitelist).where(Whitelist.scope == a.name)),
            "has_roster": db.scalar(select(func.count()).select_from(Student).where(Student.name.is_not(None))) > 0,
            "rescanning": M.worker is not None and a.name in M.worker.busy_assignments,
            "compared": {"seed": compared["seed"], "reference": compared["reference"]},
            "inbox": str(get_settings().inbox / a.name),
        }


class EditAssignment(BaseModel):
    name: str = ""
    start_at: str = ""
    deadline_at: str = ""
    notes: str = ""
    rubric_text: str = ""
    max_score: float = 100


@router.put("/a/{aid}")
def edit_assignment(aid: int, body: EditAssignment):
    err = M.update_assignment(aid, body.name, body.start_at, body.deadline_at, body.notes, body.rubric_text,
                              body.max_score)
    if err:
        raise HTTPException(400, err)
    return {"ok": True}


def assignment_name(aid: int) -> str:
    with session_scope() as db:
        a = db.get(Assignment, aid)
        if not a:
            raise HTTPException(404)
        return a.name


@router.delete("/a/{aid}")
def delete_assignment(aid: int):
    if M.delete_assignment(aid) is None:
        raise HTTPException(404)
    return {"ok": True}


@router.post("/a/{aid}/rescan")
def rescan(aid: int):
    M.worker.rescan_async(assignment_name(aid))
    return {"ok": True}


@router.post("/a/{aid}/retry")
def retry(aid: int):
    M.retry_failed(aid)
    return {"ok": True}


@router.post("/a/{aid}/boilerplate")
async def boilerplate(aid: int, files: list[UploadFile] = File(...)):
    name = assignment_name(aid)
    n = 0
    with tempfile.TemporaryDirectory() as tmp:
        for f in files:
            p = Path(tmp) / Path(f.filename or "brief.txt").name
            p.write_bytes(await f.read())
            n += M.add_boilerplate(p, name)
    M.worker.rescan_async(name)
    return {"fingerprints": n}


@router.get("/a/{aid}/clusters")
def cluster_groups(aid: int):
    with session_scope() as db:
        a = db.get(Assignment, aid)
        if not a:
            raise HTTPException(404)
        return {"assignment": {"id": a.id, "name": a.name}, "groups": [
            {"hub": c["hub"], "members": [{"id": n, "filename": c["subs"][n].filename,
                                           "tier": (c["subs"][n].report_json or {}).get("tier")} for n in c["members"]],
             "edges": [{"a": c["subs"][e["a"]].filename, "b": c["subs"][e["b"]].filename, "items": e["items"],
                        "weight": e["weight"]} for e in sorted(c["edges"], key=lambda e: -e["weight"])]}
            for c in clusters(db, aid)]}


@router.get("/a/{aid}/calibrate")
def calibrate(aid: int):
    with session_scope() as db:
        a = db.get(Assignment, aid)
        if not a:
            raise HTTPException(404)
        subs = db.scalars(select(Submission).where(Submission.assignment_id == aid, Submission.status == "done",
                                                   Submission.is_reference.is_(False))).all()
        cov = [(s.report_json or {}).get("coverage", 0) for s in subs]
        top = [((s.report_json or {}).get("by_source") or [{"share": 0}])[0]["share"] for s in subs]
        ms = db.scalars(select(Match).join(Submission, Submission.id == Match.submission_id)
                        .where(Submission.assignment_id == aid)).all()
        dist = [m.detail_json.get("distance", 0) for m in ms if m.kind == "image_hash"]
        cont = [m.score for m in ms if m.kind in ("ocr_text", "code_structure")]
        s = get_settings()
        return {"assignment": {"id": a.id, "name": a.name}, "n": len(subs), "charts": [
            {"title": "Coverage per submission", "hist": M.histogram(cov), "cut": M.outlier_cutoff(cov),
             "current": s.tier_medium_coverage, "setting": "tier_medium_coverage", "fmt": "pct"},
            {"title": "Largest single-source share", "hist": M.histogram(top), "cut": M.outlier_cutoff(top),
             "current": s.single_source_high, "setting": "single_source_high", "fmt": "pct"},
            {"title": "Text containment of matched passages", "hist": M.histogram(cont), "cut": None,
             "current": s.text_containment_min, "setting": "text_containment_min", "fmt": "pct"},
            {"title": "Image hash distance of matched images (bits)",
             "hist": M.histogram(dist, bins=s.phash_near + 1, lo=0, hi=s.phash_near + 1), "cut": None,
             "current": s.phash_near, "setting": "phash_near", "fmt": "int"}]}


# ---------------- submission (grader + integrity) ----------------

def match_text(m: Match) -> str:
    d = m.detail_json or {}
    if m.kind == "image_hash":
        return "same image" + (f", {d['variant'].replace('_', ' ')}" if d.get("variant", "orig") != "orig" else "")
    if m.kind == "image_feature":
        return "same image, cropped or resized"
    if m.kind == "code_structure":
        return "same code structure"
    return f"{m.score:.0%} same text"


@router.get("/s/{sid}")
def submission(sid: int, tier: str = "", status: str = "", q: str = "", grade: str = ""):
    with session_scope() as db:
        sub = db.get(Submission, sid)
        if not sub:
            raise HTTPException(404)
        a = sub.assignment
        report = sub.report_json or {}
        items = db.scalars(select(Item).where(Item.submission_id == sid).order_by(Item.page, Item.idx)).all()
        matches = db.scalars(select(Match).where(Match.submission_id == sid)).all()
        others = {s.id: s for s in db.scalars(select(Submission).where(
            Submission.id.in_({m.other_submission_id for m in matches})))}
        by_item = defaultdict(list)
        for m in sorted(matches, key=lambda m: -m.score):
            by_item[m.item_id].append(m)
        weights, dfs = report.get("item_weights", {}), report.get("item_df", {})
        flags = sorted(db.scalars(select(Flag).where(Flag.submission_id == sid)).all(),
                       key=lambda f: {"high": 0, "medium": 1, "low": 2}.get(f.severity, 3))
        reviews = db.scalars(select(Review).where(Review.submission_id == sid).order_by(Review.ts.desc())).all()
        top_ids = [b["submission_id"] for b in report.get("by_source", [])[:4]]
        info = lambda x: ((x.pdf_meta_json or {}).get("info", {}))  # noqa: E731
        meta_rows = [[k, info(sub).get(k, "")] + [info(others[o]).get(k, "") if o in others else "" for o in top_ids]
                     for k in ["producer", "creator", "author", "creationDate", "modDate"]]
        job = db.scalar(select(Job).where(Job.submission_id == sid))
        verify = M.verification(sub, flags, reviews[0] if reviews else None) if sub.status == "done" else None
        # Previous/next follow the list as filtered on the dashboard (same tier, status, search and grade filters).
        filtered = bool(tier or status or q or grade)
        queue = [r["sub"].id for r in M.dashboard_rows(db, sub.assignment_id, tier, "awaiting", q, grade)
                 if r["sub"].id != sid]
        everyone = [r for r in M.dashboard_rows(db, sub.assignment_id) if r["gradable"]]
        roster = [r for r in M.dashboard_rows(db, sub.assignment_id, tier, status, q, grade) if r["gradable"]] \
            if filtered else everyone
        ids = [r["sub"].id for r in roster]
        marks_by_id = {r["sub"].id: r["mark"] for r in everyone}
        if sid in ids:
            pos = ids.index(sid)
            prev_id, next_id = (ids[pos - 1] if pos > 0 else None), (ids[pos + 1] if pos < len(ids) - 1 else None)
            after = ids[pos + 1:] + ids[:pos]
        else:  # this one just left the filter (for example it was graded): carry on from where it sat in the full list
            pos = -1
            all_ids = [r["sub"].id for r in everyone]
            i = all_ids.index(sid) if sid in all_ids else 0
            keep = set(ids)
            later = [x for x in all_ids[i + 1:] if x in keep]
            earlier = [x for x in all_ids[:i] if x in keep]
            prev_id, next_id = (earlier[-1] if earlier else None), (later[0] if later else None)
            after = later + earlier
        ungraded = [x for x in after if not (marks_by_id.get(x) and marks_by_id[x].status == "released")]
        mark = db.get(Mark, sid)
        return {
            "id": sub.id, "filename": sub.filename, "page_count": sub.page_count, "status": sub.status,
            "is_seed": sub.is_seed, "is_reference": sub.is_reference, "error": (job.error or "")[:300] if job else "",
            "assignment": {"id": a.id, "name": a.name, "max_score": a.max_score, "rubric": M.rubric(a)},
            "student": student_json(sub.student), "verify": verify,
            "nav": {"pos": pos, "count": len(ids), "prev": prev_id, "next": next_id, "filtered": filtered,
                    "next_ungraded": ungraded[0] if ungraded else None, "next_flagged": queue[0] if queue else None},
            "report": {"tier": report.get("tier"), "reasons": report.get("reasons", []),
                       "coverage": report.get("coverage"), "population": report.get("population"),
                       "by_source": report.get("by_source", [])[:10]},
            "flags": [{"type": f.type, "severity": f.severity, "summary": (f.evidence_json or {}).get("summary", ""),
                       "help": FLAG_HELP.get(f.type, ""), "evidence": f.evidence_json} for f in flags],
            "reviews": [{"status": r.status, "note": r.note, "ts": iso(r.ts),
                         "suggested": (r.suggestion_json or {}).get("tier")} for r in reviews],
            "mark": {"scores": mark.scores_json or {}, "total": mark.total, "feedback": mark.feedback or "",
                     "status": mark.status, "updated_at": iso(mark.updated_at)} if mark else None,
            "items": [{"id": it.id, "page": it.page, "label": M._item_label(it), "weight": weights.get(str(it.id)),
                       "df": dfs.get(str(it.id)), "thumb": img(it.thumb_path), "text": (it.ocr_text or "")[:600],
                       "lines": M.item_lines(it)[:120],
                       "matched": bool(by_item.get(it.id) and weights.get(str(it.id))),
                       "matches": [{"id": m.id, "filename": others[m.other_submission_id].filename,
                                    "submission_id": m.other_submission_id, "what": match_text(m)}
                                   for m in by_item.get(it.id, [])]}
                      for it in items if it.is_content],
            "meta": {"heads": [others[o].filename for o in top_ids if o in others], "rows": meta_rows},
        }


class StudentBody(BaseModel):
    student_id: str
    name: str = ""


@router.put("/s/{sid}/student")
def student(sid: int, body: StudentBody):
    M.set_student(sid, body.student_id, body.name)
    return {"ok": True}


class MarkBody(BaseModel):
    scores: dict[str, str] = {}
    feedback: str = ""
    action: str = "save"  # save | release | unrelease


@router.post("/s/{sid}/mark")
def mark(sid: int, body: MarkBody):
    err, state = M.apply_mark(sid, body.scores, body.feedback, "save" if body.action == "unrelease" else body.action)
    if err:
        raise HTTPException(400, err)
    return {"status": state}


class ReviewBody(BaseModel):
    status: str
    note: str = ""


@router.post("/s/{sid}/review")
def review(sid: int, body: ReviewBody):
    if body.status not in M.DECISIONS and body.status != "unreviewed":
        raise HTTPException(400, "Unknown decision")
    if body.status == "confirmed" and not body.note.strip():
        raise HTTPException(400, "Add a note saying what needs follow-up.")
    M.review(sid, body.status, body.note)
    return {"ok": True}


class IgnoreText(BaseModel):
    lines: list[int]


@router.post("/item/{iid}/ignore-text")
def ignore_item_text(iid: int, body: IgnoreText):
    r = M.ignore_text(iid, body.lines)
    if r is None:
        raise HTTPException(404)
    if r.startswith("!"):
        raise HTTPException(400, r[1:])
    return {"ok": True}


@router.post("/item/{iid}/ignore")
def ignore_item(iid: int):
    M.ignore_item(iid, "/")
    return {"ok": True}


@router.get("/m/{mid}")
def compare(mid: int):
    with session_scope() as db:
        m = db.get(Match, mid)
        if not m:
            raise HTTPException(404)
        a, b = db.get(Item, m.item_id), db.get(Item, m.other_item_id)
        sa, sb = db.get(Submission, m.submission_id), db.get(Submission, m.other_submission_id)
        passages = V.text_passages(a.norm_text, b.norm_text)
        ha = V.highlight(a.norm_text, [p["a"] for p in passages])
        hb = V.highlight(b.norm_text, [p["b"] for p in passages])
        siblings = db.scalars(select(Match).where(Match.submission_id == m.submission_id,
                                                  Match.other_submission_id == m.other_submission_id)
                              .order_by(Match.item_id)).all()
        d = m.detail_json or {}

        def panel(it, s, h):
            return {"item_id": it.id, "lines": M.item_lines(it)[:120],
                    "submission_id": s.id, "filename": s.filename, "label": M._item_label(it), "thumb": img(it.thumb_path),
                    "text_title": "Text read from the image" if it.thumb_path else "Typed text",
                    "chunks": [[c, hit] for c, hit in h] if it.norm_text else []}

        return {"id": m.id, "kind": m.kind, "summary": compare_summary(m.kind, d),
                "assignment": {"id": sa.assignment.id, "name": sa.assignment.name},
                "siblings": [x.id for x in siblings], "a": panel(a, sa, ha), "b": panel(b, sb, hb),
                "overlay": f"/m/{m.id}/overlay.png" if a.thumb_path and b.thumb_path else None}


@router.get("/i/{iid}")
def item_page(iid: int):
    """One item and every other submission that shares it, with the reason for each match."""
    with session_scope() as db:
        it = db.get(Item, iid)
        if not it:
            raise HTTPException(404)
        sub = it.submission
        report = sub.report_json or {}
        matches = db.scalars(select(Match).where(Match.item_id == iid).order_by(Match.score.desc())).all()
        out = []
        for m in matches:
            o, os_ = db.get(Item, m.other_item_id), db.get(Submission, m.other_submission_id)
            d = m.detail_json or {}
            shared = [p["text"][:160] for p in V.text_passages(it.norm_text, o.norm_text)[:3]] if (
                m.kind == "ocr_text" and it.norm_text and o.norm_text) else []
            out.append({"match_id": m.id, "submission_id": os_.id, "filename": os_.filename,
                        "student": student_json(os_.student), "item_id": o.id, "page": o.page,
                        "label": M._item_label(o), "thumb": img(o.thumb_path), "kind": m.kind,
                        "what": match_text(m), "why": compare_summary(m.kind, d).replace(" Shared passages are highlighted.", ""), "shared": shared,
                        "lines": M.item_lines(o)[:6]})
        return {"item": {"id": it.id, "page": it.page, "label": M._item_label(it), "thumb": img(it.thumb_path),
                         "lines": M.item_lines(it)[:120], "kinds": sorted({x["kind"] for x in out}),
                         "weight": (report.get("item_weights") or {}).get(str(iid)),
                         "df": (report.get("item_df") or {}).get(str(iid))},
                "submission": {"id": sub.id, "filename": sub.filename, "student": student_json(sub.student)},
                "assignment": {"id": sub.assignment.id, "name": sub.assignment.name},
                "matches": out}


VARIANT = {"flip_h": "mirrored", "flip_v": "flipped", "rot90": "rotated", "rot180": "rotated", "rot270": "rotated",
           "invert": "colour-inverted"}


def compare_summary(kind: str, d: dict) -> str:
    if kind == "image_hash":
        v = d.get("variant", "orig")
        text = "The two images look the same" + (f" once one is {VARIANT.get(v, v)}" if v != "orig" else "")
        text += f": their fingerprints differ by {d.get('distance')} of 144 points"
        return text + (f", and {d['inliers']} feature points line up." if "inliers" in d else ".")
    if kind == "image_feature":
        return f"{d.get('inliers')} feature points line up between the images, so one is likely a crop or resize of the other."
    if kind == "code_structure":
        return ("The code has the same structure once variable names and spacing are ignored. "
                f"{d.get('containment', 0):.0%} of it appears in the other file.")
    return f"{d.get('containment', 0):.0%} of this text appears in the other file. Shared passages are highlighted."


# ---------------- settings ----------------

@router.get("/settings")
def settings():
    s = get_settings()
    from checker.core.ocr import available_engines
    with session_scope() as db:
        roster = db.scalar(select(func.count()).select_from(Student).where(Student.name.is_not(None)))
        wl = db.execute(select(Whitelist.kind, Whitelist.scope, Whitelist.reason, func.count())
                        .group_by(Whitelist.kind, Whitelist.scope, Whitelist.reason)).all()
    return {"fields": [{"name": k, "value": getattr(s, k), "help": h, "type": type(getattr(s, k)).__name__}
                       for k, h in M.EDITABLE.items()],
            "roster": roster, "engines": available_engines(),
            "ignored": [{"kind": k, "scope": sc, "reason": r, "pieces": n} for k, sc, r, n in wl]}


class SettingsBody(BaseModel):
    values: dict[str, str]


@router.put("/settings")
def save_settings(body: SettingsBody):
    s = get_settings()
    values = {}
    for k, raw in body.values.items():
        if k not in M.EDITABLE:
            continue
        try:
            values[k] = type(getattr(s, k))(raw.strip())
        except ValueError:
            raise HTTPException(400, f"Invalid value for {k}") from None
    save_overrides(values)
    return {"ok": True}


@router.post("/settings/roster")
async def roster(file: UploadFile = File(...)):
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "roster.csv"
        p.write_bytes(await file.read())
        try:
            with session_scope() as db:
                n = load_roster(db, p)
        except (UnicodeDecodeError, csv.Error, KeyError):
            raise HTTPException(400, "Could not read roster CSV") from None
    return {"loaded": n}


class EraseBody(BaseModel):
    confirm: str = ""


@router.post("/settings/erase")
def erase(body: EraseBody):
    if body.confirm.strip().lower() != "erase":
        raise HTTPException(400, "Nothing was erased. Type erase to confirm.")
    M.erase_all("erase")
    return {"ok": True}


class IgnoredBody(BaseModel):
    kind: str
    scope: str = ""
    reason: str = ""


@router.post("/settings/whitelist/delete")
def whitelist_delete(body: IgnoredBody):
    M.whitelist_delete(body.kind, body.reason, body.scope)
    return {"ok": True}
