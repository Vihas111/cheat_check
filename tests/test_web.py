"""Web app smoke test: create assignment, upload two copies, wait for the worker, open every page."""

import time

import pytest
from fastapi.testclient import TestClient

from checker.core import ocr
from tests.synth.generate import make_pdf, screenshot


@pytest.fixture
def client(data_dir, monkeypatch, tmp_path):
    monkeypatch.setenv("CHECKER_OCR_ENGINE", "none")  # hashes only; keeps the test fast
    ocr.get_engine.cache_clear()
    from checker.app import main
    from checker.app.main import app

    monkeypatch.setattr(main, "SPA", tmp_path / "no-spa")  # these tests cover the server-rendered pages

    with TestClient(app) as c:
        yield c
    ocr.get_engine.cache_clear()


def test_upload_to_review(client, tmp_path, data_dir):
    r = client.get("/")
    assert r.status_code == 200 and "Create assignment" in r.text
    r = client.post("/assignments", data={"name": "HW1"}, follow_redirects=False)
    aid = r.headers["location"].rsplit("/", 1)[1]

    shots = [screenshot([f"line {i} of a unique program output {i * 7}"] * 3, seed=i) for i in range(3)]
    for sid in ("A1", "B2"):
        make_pdf(tmp_path / f"{sid}_hw.pdf", [shots])
    files = [("files", (f"{s}_hw.pdf", (tmp_path / f"{s}_hw.pdf").read_bytes(), "application/pdf"))
             for s in ("A1", "B2")] + [("files", ("notes.txt", b"hi", "text/plain"))]
    r = client.post(f"/a/{aid}/upload", files=files, data={"mode": "submission"})
    assert r.json()["added"] == ["A1_hw.pdf", "B2_hw.pdf"] and r.json()["errors"]

    for _ in range(120):
        st = client.get(f"/api/a/{aid}/status").json()
        if st["done"] == 2:
            break
        time.sleep(0.5)
    assert st["done"] == 2, st

    page = client.get(f"/a/{aid}").text
    assert "Strong overlap" in page and "B2_hw.pdf" in page
    assert "submissions await" in page  # both copies are flagged and wait for a person
    assert client.get(f"/a/{aid}?partial=1").status_code == 200
    from sqlalchemy import select

    from checker.core.db import Match, Submission, session_scope
    with session_scope() as db:
        sid = db.scalar(select(Submission.id).where(Submission.filename == "B2_hw.pdf"))
        mid = db.scalar(select(Match.id).where(Match.submission_id == sid))
    r = client.get(f"/s/{sid}")
    assert r.status_code == 200 and "A1_hw.pdf" in r.text
    assert client.get(f"/m/{mid}").status_code == 200
    assert client.get(f"/m/{mid}/overlay.png").headers["content-type"] == "image/png"
    for url in (f"/a/{aid}/clusters", f"/a/{aid}/calibrate", f"/a/{aid}/setup", "/settings", "/new"):
        assert client.get(url).status_code == 200, url
    assert "B2_hw.pdf" in client.get(f"/a/{aid}/export.csv").text

    # the app only suggests: flagged rows stay "awaiting" until a person decides
    csv_rows = client.get(f"/a/{aid}/export.csv").text.splitlines()
    assert "suggested_tier" in csv_rows[0] and all(",awaiting,," in row for row in csv_rows[1:])
    # grading: rubric, PDF viewer, and no release while the integrity check awaits a decision
    client.post(f"/a/{aid}/edit", data={"rubric_text": "Part A | 6\nPart B | 4"})
    assert client.get(f"/s/{sid}/pdf").headers["content-type"] == "application/pdf"
    r = client.post(f"/s/{sid}/mark", data={"score_0": "7", "score_1": "4", "action": "save"})
    assert "enter a number from 0 to 6" in r.text
    r = client.post(f"/s/{sid}/mark", data={"score_0": "5", "score_1": "3.5", "action": "release"})
    assert "Record your integrity decision" in r.text
    assert ",draft,8.5,10,5,3.5," in client.get(f"/a/{aid}/grades.csv").text

    r = client.post(f"/s/{sid}/review", data={"status": "confirmed", "note": " "})
    assert "Add a note" in r.text  # follow-up needs a written reason
    r = client.post(f"/s/{sid}/review", data={"status": "false_positive", "note": "same lab group"})
    assert "Decision saved: Wrong match" in r.text
    assert "You decided: Wrong match" in r.text
    assert ",decided,Wrong match,same lab group," in client.get(f"/a/{aid}/export.csv").text
    assert f"/s/{sid}\"" not in client.get(f"/a/{aid}?partial=1&status=awaiting").text
    r = client.post(f"/s/{sid}/mark", data={"score_0": "5", "score_1": "3.5", "action": "release"})
    assert ",released,8.5,10," in client.get(f"/a/{aid}/grades.csv").text

    # navigation: the home screen lists assignments; renaming keeps the inbox folder and ignored content with it
    assert "HW1" in client.get("/").text
    (data_dir / "inbox" / "HW1").mkdir(parents=True, exist_ok=True)
    r = client.post(f"/a/{aid}/edit", data={"name": "HW1 final", "rubric_text": "Part A | 6\nPart B | 4"})
    assert "Saved." in r.text and (data_dir / "inbox" / "HW1 final").is_dir()
    r = client.post(f"/s/{sid}/student", data={"student_id": "s999", "name": "Pat Doe"})
    assert "Pat Doe" in r.text and "Student saved" in r.text
    assert client.get("/img/../checker.db").status_code == 404


def test_parse_rubric():
    from checker.app.main import parse_rubric
    assert parse_rubric("Part A: table | 10\n\nPart B | 2.5") == [
        {"name": "Part A: table", "points": 10}, {"name": "Part B", "points": 2.5}]
    assert parse_rubric("  ") is None
    for bad in ("Part A | 0", "A | 1\nA | 2", "no points here"):
        with pytest.raises(ValueError):
            parse_rubric(bad)


def test_erase_all(client, data_dir):
    client.post("/assignments", data={"name": "HW9"})
    (data_dir / "pdfs").mkdir(exist_ok=True)
    (data_dir / "pdfs" / "x.pdf").write_bytes(b"%PDF")
    assert "Nothing was erased" in client.post("/settings/erase", data={"confirm": "yes"}).text
    assert "HW9" in client.get("/?new=1").text
    assert "All data erased" in client.post("/settings/erase", data={"confirm": "Erase"}).text
    assert "HW9" not in client.get("/?new=1").text and not (data_dir / "pdfs").exists()
