"""Deleting one assignment removes only its own data."""

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


def _upload(client, tmp_path, aid, sid, seed):
    shots = [screenshot([f"unique output {seed} {i * 7}"] * 3, seed=seed + i) for i in range(2)]
    f = tmp_path / f"{sid}_hw.pdf"
    make_pdf(f, [shots])
    files = [("files", (f.name, f.read_bytes(), "application/pdf"))]
    client.post(f"/a/{aid}/upload", files=files, data={"mode": "submission"})


def _wait(client, aid, n):
    for _ in range(120):
        if client.get(f"/api/a/{aid}/status").json()["done"] == n:
            return
        time.sleep(0.5)
    raise AssertionError("not processed")


def test_delete_one_assignment(client, tmp_path, data_dir):
    a = client.post("/api/assignments", json={"name": "LAB1"}).json()["id"]
    b = client.post("/api/assignments", json={"name": "LAB2"}).json()["id"]
    _upload(client, tmp_path, a, "S1", 10)
    _upload(client, tmp_path, b, "S2", 50)
    _wait(client, a, 1)
    _wait(client, b, 1)
    assert client.get(f"/api/a/{a}").json()["total"] == 1

    assert client.delete(f"/api/a/{a}").json() == {"ok": True}
    assert client.delete(f"/api/a/{a}").status_code == 404
    assert [x["name"] for x in client.get("/api/assignments").json()] == ["LAB2"]
    page = client.get(f"/api/a/{b}").json()
    assert len(page["rows"]) == 1 and page["counts"]["done"] == 1
