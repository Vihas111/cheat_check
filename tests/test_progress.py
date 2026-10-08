from checker.core import progress


def test_progress_steps_and_eta(monkeypatch):
    assert progress.snapshot("X") is None
    progress.start("X")
    assert progress.snapshot("X")["phase"] == "Starting"
    t = [100.0]
    monkeypatch.setattr(progress.time, "time", lambda: t[0])
    progress.update("X", 3, 0, 10, "a.pdf")
    t[0] = 106.0
    progress.update("X", 3, 3, 10, "d.pdf")
    s = progress.snapshot("X")
    assert (s["step"], s["phase"], s["done"], s["total"], s["file"]) == (3, "Comparing submissions", 3, 10, "d.pdf")
    assert s["eta_s"] == 14  # 6 s for 3 files, 7 left
    progress.update("X", 4, 0, 10)
    assert progress.snapshot("X")["phase"] == "Scoring results" and progress.snapshot("X")["eta_s"] is None
    progress.finish("X")
    assert progress.snapshot("X") is None
