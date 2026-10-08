"""PDF -> stored submission with items, hashes, OCR text and shingles."""

import csv
import hashlib
import logging
import re
import shutil
import threading
from pathlib import Path

from sqlalchemy import delete, select

from checker.config import PIPELINE_VERSION, get_settings
from checker.core import fingerprint as fp
from checker.core import regions
from checker.core.db import Assignment, Entity, Item, Job, Shingle, Student, Submission, Whitelist, session_scope
from checker.core.entities import extract_entities
from checker.core.normalize import normalize_text
from checker.core.ocr import get_engine
from checker.core.pdf_extract import ExtractedSubmission, extract

log = logging.getLogger(__name__)


def get_assignment(session, name: str) -> Assignment:
    a = session.scalar(select(Assignment).where(Assignment.name == name))
    if not a:
        a = Assignment(name=name)
        session.add(a)
        session.flush()
    return a


def load_roster(session, csv_path: Path) -> int:
    """Upsert students from a CSV with columns student_id,name,username,email."""
    n = 0
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            sid = (row.get("student_id") or "").strip()
            if not sid:
                continue
            st = session.scalar(select(Student).where(Student.student_id == sid)) or Student(student_id=sid)
            st.name, st.username, st.email = (row.get(k, "").strip() or None for k in ("name", "username", "email"))
            session.add(st)
            n += 1
    return n


def find_srns(text: str) -> list[str]:
    return [m.upper() for m in re.findall(get_settings().srn_regex, text or "", re.I)]


def student_id_from_filename(filename: str) -> str:
    srns = find_srns(filename)
    if srns:
        return srns[0]
    m = re.match(get_settings().filename_regex, filename)
    if m and m.groupdict().get("student_id"):
        return m.group("student_id")
    return Path(filename).stem


def resolve_student(session, filename: str) -> Student:
    sid = student_id_from_filename(filename)
    st = session.scalar(select(Student).where(Student.student_id == sid))
    if not st:
        st = Student(student_id=sid)
        session.add(st)
        session.flush()
    return st


def register(path: Path, assignment: str, *, force=False, seed=False, reference=False) -> tuple[int, bool]:
    """Store the PDF and create a submission + queued job. Returns (submission_id, is_new).
    Idempotent: the same file (SHA-256 + filename) in the assignment is skipped unless force."""
    s = get_settings()
    raw = Path(path).read_bytes()
    sha = hashlib.sha256(raw).hexdigest()
    with session_scope() as db:
        a = get_assignment(db, assignment)
        existing = db.scalar(select(Submission).where(Submission.assignment_id == a.id, Submission.sha256 == sha,
                                                      Submission.filename == Path(path).name))
        if existing and not force:
            return existing.id, False
        if existing:
            db.delete(existing)
            db.flush()
        store = s.data_dir / "pdfs" / f"{sha}.pdf"
        store.parent.mkdir(parents=True, exist_ok=True)
        if not store.exists():
            shutil.copyfile(path, store)
        student = None if reference else resolve_student(db, Path(path).name)
        sub = Submission(assignment_id=a.id, student_pk=student.id if student else None,
                         filename=Path(path).name, stored_path=str(store), sha256=sha,
                         status="queued", is_seed=seed, is_reference=reference)
        db.add(sub)
        db.flush()
        db.add(Job(submission_id=sub.id))
        return sub.id, True


def _save_image(im, sha: str) -> str:
    s = get_settings()
    rel = Path("images") / sha[:2] / f"{sha}.png"
    out = s.data_dir / rel
    if not out.exists():
        out.parent.mkdir(parents=True, exist_ok=True)
        im = im.copy()
        im.thumbnail((s.max_stored_side, s.max_stored_side))
        im.save(out, optimize=False)
    return str(rel)


def cached_ocr(pix_sha: str) -> dict | None:
    """Reuse OCR of a pixel-identical image seen before (template screenshots, exact copies)."""
    with session_scope() as db:
        it = db.scalar(select(Item).where(Item.sha256 == pix_sha, Item.ocr_text != "").limit(1))
        return {"text": it.ocr_text, "words": it.ocr_words_json or [], "conf": it.ocr_conf or 0.0} if it else None


def text_fingerprints(norm: str) -> dict[str, set[int]]:
    s = get_settings()
    return {"word": fp.word_shingles(norm, s.shingle_k), "line": fp.line_hashes(norm, s.min_line_chars),
            "code": fp.code_fingerprints(norm, s.code_k, s.code_w)}


def build_items(ex: ExtractedSubmission, ocr) -> list[tuple[Item, dict[str, set[int]]]]:
    """Returns (item, {word|line|code: hashes}) for every image/page_render/text_block."""
    s = get_settings()
    out = []
    for e in ex.images:
        pix_sha = fp.pixel_sha256(e.image)
        # Page renders that are not content are only kept for display; skip their OCR.
        res = {"text": "", "words": [], "conf": 0.0}
        if e.is_content:
            res = cached_ocr(pix_sha) or ocr.extract(e.image)
        norm = normalize_text(res["text"])
        h = fp.image_hashes(e.image, s.phash_size)
        item = Item(page=e.page, idx=e.idx, kind=e.kind, source=e.source, is_content=e.is_content,
                    bbox=e.bbox, width=e.image.width, height=e.image.height, sha256=pix_sha,
                    raw_sha256=e.raw_sha256, phash=h["phash"], dhash=h["dhash"], whash=h["whash"],
                    hash_variants_json=h["variants"], ocr_text=res["text"], norm_text=norm,
                    ocr_conf=res["conf"], ocr_words_json=res["words"], thumb_path=_save_image(e.image, pix_sha))
        out.append((item, text_fingerprints(norm)))
    for p in ex.pages:
        norm = normalize_text(p.text)
        if not norm:
            continue
        item = Item(page=p.number, idx=1000, kind="text_block", source="text_layer", is_content=True,
                    ocr_text=p.text, norm_text=norm, ocr_conf=1.0)
        out.append((item, text_fingerprints(norm)))
    return out


def process(submission_id: int, ocr=None) -> dict:
    """Heavy part of ingest: extract, OCR, fingerprint, persist. Safe to re-run (clears old items)."""
    ocr = ocr or get_engine()
    with session_scope() as db:
        sub = db.get(Submission, submission_id)
        path = Path(sub.stored_path)
    ex = extract(path)
    built = build_items(ex, ocr)
    with session_scope() as db:
        sub = db.get(Submission, submission_id)
        db.execute(delete(Shingle).where(Shingle.submission_id == sub.id))
        db.execute(delete(Entity).where(Entity.submission_id == sub.id))
        db.execute(delete(Item).where(Item.submission_id == sub.id))
        sub.page_count = ex.page_count
        sub.pdf_meta_json = {**ex.meta, "skipped_images": ex.skipped_images,
                             "pages": [{"page": p.number, "path": p.path, "hidden_spans": p.hidden_spans}
                                       for p in ex.pages]}
        _identify_from_cover(db, sub, built)
        for item, _ in built:
            item.submission_id = sub.id
            db.add(item)
        db.flush()
        rows = []
        for item, prints in built:
            for kind, hashes in prints.items():
                rows += [{"hash": h, "submission_id": sub.id, "item_id": item.id, "kind": kind} for h in hashes]
            for e in extract_entities(item.ocr_text or ""):
                db.add(Entity(submission_id=sub.id, item_id=item.id, **e))
        if rows:
            db.execute(Shingle.__table__.insert(), rows)
        sub.pipeline_version = PIPELINE_VERSION
    return summarize(ex, built)


def _identify_from_cover(db, sub: Submission, built) -> None:
    """Filenames are messy. If the filename has no SRN, use the one written on the first pages."""
    if sub.is_reference or find_srns(sub.filename):
        return
    cover = " ".join(i.ocr_text or "" for i, _ in built if i.page <= 2)
    srns = find_srns(cover)
    if not srns:
        return
    srn = max(set(srns), key=srns.count)
    st = db.scalar(select(Student).where(Student.student_id == srn))
    if not st:
        st = Student(student_id=srn)
        db.add(st)
        db.flush()
    sub.student_pk = st.id


def summarize(ex: ExtractedSubmission, built) -> dict:
    return {
        "file": ex.path.name,
        "pages": ex.page_count,
        "page_paths": {p.number: p.path for p in ex.pages},
        "items": [{"page": i.page, "idx": i.idx, "kind": i.kind, "source": i.source, "content": i.is_content,
                   "size": f"{i.width}x{i.height}", "ocr_chars": len(i.norm_text or ""),
                   "shingles": sum(map(len, pr.values()))} for i, pr in built],
        "skipped_images": ex.skipped_images,
        "hidden_spans": sum(len(p.hidden_spans) for p in ex.pages),
        "producer": ex.meta["info"].get("producer"),
        "incremental_updates": ex.meta["incremental_updates"],
    }


# ponytail: one global lock around match+score so two parallel jobs never miss or double-store each other.
# OCR (the slow part) runs outside it. Per-assignment locks if several assignments ingest at once.
MATCH_LOCK = threading.Lock()


def match_and_score(submission_id: int):
    from checker.core.match import build_index, match_submission
    from checker.core.score import score_many
    with MATCH_LOCK, session_scope() as db:
        sub = db.get(Submission, submission_id)
        sub.status = "done"  # visible to the index from here on
        db.flush()
        idx = build_index(db, sub.assignment_id)
        affected = match_submission(db, sub, idx)
        score_many(db, sub.assignment_id, affected | {sub.id}, idx)


def run_job(submission_id: int, ocr=None) -> dict:
    """Full pipeline for one queued submission, with job bookkeeping. Safe to re-run after a crash."""
    with session_scope() as db:
        job = db.scalar(select(Job).where(Job.submission_id == submission_id))
        job.state, job.attempts, job.error = "processing", job.attempts + 1, None
        db.get(Submission, submission_id).status = "processing"
    try:
        summary = process(submission_id, ocr)
        with session_scope() as db:  # ignored regions apply to new files too
            regions.apply(db, db.get(Submission, submission_id).assignment_id, [submission_id])
        match_and_score(submission_id)
    except Exception as e:
        log.exception("job for submission %s failed", submission_id)
        with session_scope() as db:
            job = db.scalar(select(Job).where(Job.submission_id == submission_id))
            job.state, job.error = "failed", repr(e)
            db.get(Submission, submission_id).status = "failed"
        raise
    with session_scope() as db:
        db.scalar(select(Job).where(Job.submission_id == submission_id)).state = "done"
    return summary


def ingest_file(path: Path, assignment: str, *, force=False, seed=False, reference=False, ocr=None) -> dict:
    sub_id, is_new = register(path, assignment, force=force, seed=seed, reference=reference)
    if not is_new:
        return {"file": Path(path).name, "skipped": "already ingested", "submission_id": sub_id}
    summary = run_job(sub_id, ocr)
    with session_scope() as db:
        report = db.get(Submission, sub_id).report_json or {}
    return {**summary, "submission_id": sub_id, "file": Path(path).name, "tier": report.get("tier"),
            "coverage": report.get("coverage")}


def rescan(assignment: str, ocr=None, reprocess_all=False) -> dict:
    """Re-extract stale submissions (old pipeline_version), then re-match and re-score the whole assignment
    in ingestion order, so early submissions get the full context and current rarity weights."""
    from checker.core import progress
    from checker.core.match import build_index, match_submission
    from checker.core.score import score_many
    progress.start(assignment)
    try:
        with session_scope() as db:
            a = get_assignment(db, assignment)
            subs = db.execute(select(Submission.id, Submission.pipeline_version, Submission.status, Submission.filename)
                              .where(Submission.assignment_id == a.id).order_by(Submission.id)).all()
        stale = [(sid, fn) for sid, ver, st, fn in subs if reprocess_all or ver != PIPELINE_VERSION or st == "failed"]
        for i, (sid, fn) in enumerate(stale):
            progress.update(assignment, 1, i, len(stale), fn)
            process(sid, ocr)
            with session_scope() as db:
                db.get(Submission, sid).status = "done"
        with session_scope() as db:
            progress.update(assignment, 2, 0, 0)
            regions.apply(db, a.id, progress=lambda d, t: progress.update(assignment, 2, d, t))
        with MATCH_LOCK, session_scope() as db:
            progress.update(assignment, 3, 0, 0)
            idx = build_index(db, a.id)
            ids = sorted(idx.subs)
            names = dict(db.execute(select(Submission.id, Submission.filename).where(Submission.id.in_(ids))).all())
            for i, sid in enumerate(ids):
                progress.update(assignment, 3, i, len(ids), names.get(sid, ""))
                match_submission(db, db.get(Submission, sid), idx, max_other_id=sid)
            progress.update(assignment, 4, 0, len(ids))
            score_many(db, a.id, None, idx, on_progress=lambda d, t: progress.update(assignment, 4, d, t))
    finally:
        progress.finish(assignment)
    return {"assignment": assignment, "reprocessed": len(stale), "rescored": len(subs)}


def add_boilerplate(path: Path, assignment: str | None, ocr=None, reason="boilerplate") -> int:
    """Assignment brief / starter code: its images and text shingles are whitelisted (never matched)."""
    ocr = ocr or get_engine()
    p = Path(path)
    hashes, phashes = set(), set()
    if p.suffix.lower() == ".pdf":
        for item, prints in build_items(extract(p), ocr):
            for v in prints.values():
                hashes |= v
            if item.kind == "image" and item.phash:
                phashes.add(item.phash.hex())
    else:
        for v in text_fingerprints(normalize_text(p.read_text(encoding="utf-8", errors="replace"))).values():
            hashes |= v
    with session_scope() as db:
        for h in hashes:
            db.add(Whitelist(kind="shingle", fingerprint=str(h), scope=assignment, reason=f"{reason}: {p.name}"))
        for h in phashes:
            db.add(Whitelist(kind="image", fingerprint=h, scope=assignment, reason=f"{reason}: {p.name}"))
    return len(hashes) + len(phashes)
