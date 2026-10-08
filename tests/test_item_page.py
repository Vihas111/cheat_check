"""The item page lists every submission that shares an item, with the reason for each match."""

import time

import pytest
from fastapi.testclient import TestClient

from checker.core import ocr
from tests.synth.generate import make_pdf, screenshot


@pytest.fixture
def client(data_dir, monkeypatch):
    monkeypatch.setenv("CHECKER_OCR_ENGINE", "none")
    ocr.get_engine.cache_clear()
    from checker.app.main import app

    with TestClient(app) as c:
        yield c
    ocr.get_engine.cache_clear()


def test_item_shared_by_three(client, tmp_path):
    aid = client.post("/api/assignments", json={"name": "L"}).json()["id"]
    shared = screenshot(["the same output on three machines"] * 4, seed=99)
    for n, sid in enumerate(("A1", "B2", "C3")):
        mine = screenshot([f"only mine {n} {sid}"] * 4, seed=n)
        f = tmp_path / f"{sid}_x.pdf"
        make_pdf(f, [[shared, mine]])
        client.post(f"/a/{aid}/upload", files=[("files", (f.name, f.read_bytes(), "application/pdf"))],
                    data={"mode": "submission"})
    for _ in range(120):
        if client.get(f"/api/a/{aid}/status").json()["done"] == 3:
            break
        time.sleep(0.5)
    sid = next(r["id"] for r in client.get(f"/api/a/{aid}").json()["rows"] if r["filename"] == "A1_x.pdf")
    items = client.get(f"/api/s/{sid}").json()["items"]
    hit = next(i for i in items if i["matches"])
    page = client.get(f"/api/i/{hit['id']}").json()
    assert {m["filename"] for m in page["matches"]} == {"B2_x.pdf", "C3_x.pdf"}
    assert all(m["why"] and m["kind"] in ("image_hash", "image_feature", "ocr_text") for m in page["matches"])
    assert "image_hash" in page["item"]["kinds"] and page["submission"]["filename"] == "A1_x.pdf"
    assert client.get("/api/i/999999").status_code == 404
