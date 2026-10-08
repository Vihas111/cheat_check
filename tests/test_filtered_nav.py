"""Previous/next in the grader follow the dashboard filters; "clear" lists submissions with nothing flagged."""

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


def test_nav_follows_filter(client, tmp_path):
    aid = client.post("/api/assignments", json={"name": "L"}).json()["id"]
    shared = "Describe how the routing table of router R2 is populated when static routes are used between subnets."
    own = {"B2": "Bananas ripen faster beside apples because of the ethylene gas that apples release in storage.",
           "D4": "Granite is an igneous rock formed from slowly cooled magma deep below the surface of the earth."}
    for sid in ("A1", "B2", "C3", "D4"):
        f = tmp_path / f"{sid}_x.pdf"
        doc = pymupdf.open()
        doc.new_page().insert_textbox(pymupdf.Rect(50, 50, 545, 300), shared if sid in ("A1", "C3") else own[sid], fontsize=11)
        doc.save(f)
        client.post(f"/a/{aid}/upload", files=[("files", (f.name, f.read_bytes(), "application/pdf"))],
                    data={"mode": "submission"})
    for _ in range(120):
        if client.get(f"/api/a/{aid}/status").json()["done"] == 4:
            break
        time.sleep(0.5)
    ids = {r["filename"][:2]: r["id"] for r in client.get(f"/api/a/{aid}").json()["rows"]}

    clear = client.get(f"/api/a/{aid}?status=clear").json()
    assert sorted(r["filename"][:2] for r in clear["rows"]) == ["B2", "D4"] and clear["total"] == 4

    nav = client.get(f"/api/s/{ids['B2']}?status=clear").json()["nav"]
    assert (nav["prev"], nav["next"], nav["count"], nav["filtered"]) == (None, ids["D4"], 2, True)
    assert client.get(f"/api/s/{ids['D4']}?status=clear").json()["nav"]["prev"] == ids["B2"]

    flagged = client.get(f"/api/s/{ids['A1']}?status=awaiting").json()["nav"]
    assert flagged["next"] in (ids["C3"], None) and flagged["count"] == 2

    # a submission outside the filter still gets sensible neighbours inside it, and no filter means everyone
    outside = client.get(f"/api/s/{ids['C3']}?status=clear").json()["nav"]
    assert outside["pos"] == -1 and outside["prev"] == ids["B2"] and outside["next"] == ids["D4"]
    assert client.get(f"/api/s/{ids['B2']}").json()["nav"]["count"] == 4
