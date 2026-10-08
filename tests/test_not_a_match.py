"""Marking a pair as "not a match" removes only that pair, survives re-scans, and can be undone."""

from sqlalchemy import select

from checker.app import main as M
from checker.core.db import Match, Submission, Whitelist, session_scope
from checker.core.ingest import ingest_file, rescan
from checker.core.ocr import get_engine
from tests.synth.generate import make_pdf, screenshot


def pairs():
    with session_scope() as db:
        names = {s.id: s.filename[:2] for s in db.scalars(select(Submission))}
        return {frozenset((names[m.submission_id], names[m.other_submission_id])) for m in db.scalars(select(Match))}


def test_dismiss_one_pair(data_dir, tmp_path):
    ocr = get_engine()
    shared = screenshot(["the same output on three machines"] * 4, seed=99)
    for n, sid in enumerate(("A1", "B2", "C3")):
        f = tmp_path / f"{sid}_x.pdf"
        make_pdf(f, [[shared, screenshot([f"only mine {n} {sid}"] * 4, seed=n)]])
        ingest_file(f, "lab", ocr=ocr)
    ab, ac, bc = frozenset(("A1", "B2")), frozenset(("A1", "C3")), frozenset(("B2", "C3"))
    assert {ab, ac, bc} <= pairs()

    with session_scope() as db:
        sub_a = db.scalars(select(Submission).where(Submission.filename.like("A1%"))).one().id
        mid = db.scalars(select(Match).where(Match.submission_id == sub_a)).first()
        other = db.get(Submission, mid.other_submission_id).filename[:2]
        mid = mid.id
    out = M.dismiss_match(mid)
    assert out and out["scope"] == "lab" and out["reason"].startswith("not a match:")
    gone = frozenset(("A1", other))
    assert gone not in pairs()  # removed at once, before any re-scan
    rescan("lab")
    assert gone not in pairs() and len(pairs()) == 2  # the other two pairs are untouched, even after a re-scan

    assert M.dismiss_match(999999) is None
    with session_scope() as db:  # undo
        for w in db.scalars(select(Whitelist).where(Whitelist.kind == "pair")):
            db.delete(w)
    rescan("lab")
    assert {ab, ac, bc} <= pairs()
