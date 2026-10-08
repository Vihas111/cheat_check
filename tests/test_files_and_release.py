"""Delete single files after upload; release every draft at once (respecting the integrity rules)."""

import time

import pymupdf
import pytest
from fastapi.testclient import TestClient

from checker.core import ocr


@pytest.fixture
def client(data_dir, monkeypatch):
    monkeypatch.setenv("CHECKER_OCR_ENGINE", "none")
    ocr.get_engine.cache_clear()
    from checker.app.main import app

    with TestClient(app) as c:
        yield c
    ocr.get_engine.cache_clear()


def upload_typed(client, tmp_path, aid, texts):
    for sid, text in texts.items():
        f = tmp_path / f"{sid}_x.pdf"
        doc = pymupdf.open()
        doc.new_page().insert_textbox(pymupdf.Rect(50, 50, 545, 300), text, fontsize=11)
        doc.save(f)
        client.post(f"/a/{aid}/upload", files=[("files", (f.name, f.read_bytes(), "application/pdf"))],
                    data={"mode": "submission"})
    for _ in range(120):
        if client.get(f"/api/a/{aid}/status").json()["done"] == len(texts):
            return
        time.sleep(0.5)
    raise AssertionError("not processed")


SHARED = "Describe how the routing table of router R2 is populated when static routes are used between subnets."
TEXTS = {"A1": SHARED, "B2": "Bananas ripen faster beside apples because of the ethylene gas that apples release.",
         "C3": SHARED, "D4": "Granite is an igneous rock formed from slowly cooled magma deep below the surface."}


def test_release_all_drafts_and_delete_file(client, tmp_path, data_dir):
    aid = client.post("/api/assignments", json={"name": "L", "rubric_text": "Part A | 6\nPart B | 4"}).json()["id"]
    upload_typed(client, tmp_path, aid, TEXTS)
    ids = {r["filename"][:2]: r["id"] for r in client.get(f"/api/a/{aid}").json()["rows"]}
    for k in ("A1", "B2", "C3"):  # drafts: A1 and C3 are flagged, B2 is clean
        client.post(f"/api/s/{ids[k]}/mark", json={"scores": {"Part A": "5", "Part B": "3"}})
    client.post(f"/api/s/{ids['D4']}/mark", json={"scores": {"Part A": "5"}})  # incomplete
    assert client.get(f"/api/a/{aid}").json()["grades"]["draft"] == 4

    r = client.post(f"/api/a/{aid}/release-drafts").json()
    held = {h["filename"][:2]: h["reason"] for h in r["held"]}
    assert r["released"] == 1 and set(held) == {"A1", "C3", "D4"}
    assert "integrity decision" in held["A1"] and "Part B" in held["D4"]
    assert client.get(f"/api/a/{aid}").json()["grades"] == {"released": 1, "draft": 3}

    client.post(f"/api/s/{ids['A1']}/review", json={"status": "false_positive"})  # decision, then release again
    r = client.post(f"/api/a/{aid}/release-drafts").json()
    assert r["released"] == 1 and {h["filename"][:2] for h in r["held"]} == {"C3", "D4"}

    # delete one uploaded file: it goes, the others stay, its stored pdf is removed
    n_pdfs = len(list((data_dir / "pdfs").glob("*.pdf")))
    assert client.post(f"/api/a/{aid}/delete-files", json={"ids": [ids["C3"]]}).json()["deleted"] == 1
    rows = client.get(f"/api/a/{aid}").json()["rows"]
    assert sorted(r["filename"][:2] for r in rows) == ["A1", "B2", "D4"]
    assert len(list((data_dir / "pdfs").glob("*.pdf"))) == n_pdfs - 1
    assert client.post(f"/api/a/{aid}/delete-files", json={"ids": [ids["C3"]]}).status_code == 404
    assert client.post(f"/api/a/{aid}/delete-files", json={"ids": [999]}).status_code == 404
