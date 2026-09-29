"""End-to-end: synthetic corpus (plan.md §14 cases 1-8) through ingest, matching, scoring, rescan.
Slow (~1-2 min): real OCR on ~90 screenshots."""

import pytest
from sqlalchemy import select

from checker import config
from checker.core import db
from checker.core.cluster import clusters
from checker.core.db import Flag, Match, Submission, session_scope
from checker.core.ingest import ingest_file, load_roster, rescan
from checker.core.ocr import get_engine
from tests.synth.corpus import build, evaluate, summary


def results() -> dict:
    out = {}
    with session_scope() as s:
        subs = {x.id: x for x in s.scalars(select(Submission))}
        for x in subs.values():
            ms = s.scalars(select(Match).where(Match.submission_id == x.id)).all()
            out[x.filename] = {
                "tier": (x.report_json or {}).get("tier"),
                "flags": {f.type for f in s.scalars(select(Flag).where(Flag.submission_id == x.id))},
                "sources": {subs[m.other_submission_id].filename for m in ms},
                "match_kinds": {m.kind for m in ms},
            }
    return out


@pytest.fixture(scope="module")
def corpus(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("corpus")
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("CHECKER_DATA_DIR", str(tmp / "data"))
        config.get_settings.cache_clear()
        db.init_db()
        expected = build(tmp / "pdfs")
        with session_scope() as s:
            load_roster(s, tmp / "pdfs" / "roster.csv")
        ocr = get_engine("rapidocr")
        files = sorted((tmp / "pdfs").glob("*.pdf"), key=lambda p: (p.name[0] == "C", p.name))
        for f in files:
            ingest_file(f, "A1", ocr=ocr)
        yield tmp, expected, files, ocr
        config.get_settings.cache_clear()
        db._Session = None


def _check(expected):
    rows = evaluate(expected, results())
    print("\n" + summary(rows))
    bad = [r for r in rows if not r["ok"]]
    assert not bad, bad


def test_incremental_ingest_flags_expected_cases(corpus):
    _, expected, _, _ = corpus
    _check(expected)


def test_reingest_is_noop(corpus):
    _, _, files, ocr = corpus
    assert ingest_file(files[0], "A1", ocr=ocr)["skipped"] == "already ingested"


def test_rescan_keeps_results(corpus):
    _, expected, _, ocr = corpus
    assert rescan("A1", ocr)["reprocessed"] == 0
    _check(expected)


def test_clusters_group_copies(corpus):
    with session_scope() as s:
        cl = clusters(s, 1)
        names = [{sub.filename for sub in c["subs"].values()} for c in cl]
    assert any({"S01_hw.pdf", "C1_hw.pdf"} <= n for n in names)
    assert any({"C4_hw.pdf", "S04_hw.pdf", "S05_hw.pdf", "S06_hw.pdf"} <= n for n in names)
    assert not any("H1_hw.pdf" in n for n in names)
