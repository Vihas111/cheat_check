"""JSON API smoke test: the flow the React front end drives (create, upload, grade, decide, compare, settings)."""

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


def test_api_flow(client, tmp_path):
    assert client.get("/api/assignments").json() == []
    r = client.post("/api/assignments", json={"name": "HW1", "rubric_text": "Part A | 6\nPart B | 4"})
    aid = r.json()["id"]
    assert client.post("/api/assignments", json={"name": " "}).status_code == 400

    shots = [screenshot([f"line {i} of a unique program output {i * 7}"] * 3, seed=i) for i in range(3)]
    for sid in ("A1", "B2"):
        make_pdf(tmp_path / f"{sid}_hw.pdf", [shots])
    files = [("files", (f"{s}_hw.pdf", (tmp_path / f"{s}_hw.pdf").read_bytes(), "application/pdf")) for s in ("A1", "B2")]
    assert client.post(f"/a/{aid}/upload", files=files, data={"mode": "submission"}).json()["added"]
    for _ in range(120):
        if client.get(f"/api/a/{aid}/status").json()["done"] == 2:
            break
        time.sleep(0.5)

    page = client.get(f"/api/a/{aid}").json()
    assert page["assignment"]["rubric"] == [{"name": "Part A", "points": 6.0}, {"name": "Part B", "points": 4.0}]
    assert len(page["rows"]) == 2 and page["verify"]["awaiting"] == 2
    assert len(client.get(f"/api/a/{aid}?status=awaiting&q=b2").json()["rows"]) == 1
    sid = next(r["id"] for r in page["rows"] if r["filename"] == "B2_hw.pdf")

    sub = client.get(f"/api/s/{sid}").json()
    assert sub["verify"] == "awaiting" and sub["report"]["tier"] == "HIGH" and sub["nav"]["count"] == 2
    mid = next(m["id"] for it in sub["items"] for m in it["matches"])

    # a flagged submission cannot be released before an integrity decision; a bad number saves nothing
    ok = {"Part A": "5", "Part B": "3"}
    assert client.post(f"/api/s/{sid}/mark", json={"scores": {"Part A": "9"}}).status_code == 400
    assert client.post(f"/api/s/{sid}/mark", json={"scores": ok, "action": "release"}).status_code == 400
    assert client.post(f"/api/s/{sid}/mark", json={"scores": ok, "feedback": "good"}).json() == {"status": "draft"}
    assert client.get(f"/api/s/{sid}").json()["mark"]["total"] == 8.0
    assert client.post(f"/api/s/{sid}/review", json={"status": "confirmed"}).status_code == 400
    assert client.post(f"/api/s/{sid}/review", json={"status": "false_positive"}).status_code == 200
    assert client.post(f"/api/s/{sid}/mark", json={"scores": ok, "action": "release"}).json() == {"status": "released"}
    assert client.get(f"/api/s/{sid}").json()["verify"] == "decided"

    cmp = client.get(f"/api/m/{mid}").json()
    assert cmp["summary"] and cmp["a"]["filename"] and cmp["b"]["filename"]
    assert client.get(f"/api/a/{aid}/clusters").json()["groups"]
    assert len(client.get(f"/api/a/{aid}/calibrate").json()["charts"]) == 4

    assert client.put(f"/api/a/{aid}", json={"name": "HW1", "rubric_text": "bad"}).status_code == 400
    assert client.put(f"/api/a/{aid}", json={"name": "HW1", "notes": "n", "max_score": 50}).status_code == 200

    st = client.get("/api/settings").json()
    assert any(f["name"] == "phash_near" for f in st["fields"])
    assert client.put("/api/settings", json={"values": {"phash_near": "x"}}).status_code == 400
    assert client.post("/api/settings/erase", json={"confirm": "no"}).status_code == 400
    assert client.post("/api/settings/erase", json={"confirm": "erase"}).status_code == 200
    assert client.get("/api/assignments").json() == []
