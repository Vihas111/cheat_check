"""Live progress of a re-scan, per assignment name. Read by the status endpoint so the page can show real numbers."""

import threading
import time

_lock = threading.Lock()
_state: dict[str, dict] = {}

STEPS = ["Re-reading changed files", "Comparing submissions", "Scoring results"]


def start(assignment: str) -> None:
    with _lock:
        _state[assignment] = {"step": 0, "phase": "Starting", "done": 0, "total": 0, "file": "", "t0": time.time(),
                              "steps": len(STEPS)}


def update(assignment: str, step: int, done: int, total: int, file: str = "") -> None:
    """step is 1-based; a new step restarts the clock used for the time estimate."""
    with _lock:
        s = _state.get(assignment)
        if not s:
            return
        if s["step"] != step:
            s.update(step=step, phase=STEPS[step - 1], t0=time.time())
        s.update(done=done, total=total, file=file)


def finish(assignment: str) -> None:
    with _lock:
        _state.pop(assignment, None)


def snapshot(assignment: str) -> dict | None:
    with _lock:
        s = _state.get(assignment)
        if not s:
            return None
        out = {k: s[k] for k in ("step", "steps", "phase", "done", "total", "file")}
        elapsed = time.time() - s["t0"]
        out["eta_s"] = round(elapsed / s["done"] * (s["total"] - s["done"])) if s["done"] >= 3 and s["total"] else None
        return out
