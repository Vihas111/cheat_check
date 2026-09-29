"""Background job runner + inbox watcher. Jobs live in the DB, so a restart resumes unfinished work."""

import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from sqlalchemy import select, update

from checker.config import get_settings
from checker.core.db import Job, Submission, session_scope
from checker.core.ingest import register, rescan, run_job

log = logging.getLogger(__name__)


class Worker:
    def __init__(self):
        s = get_settings()
        self.pool = ThreadPoolExecutor(max_workers=s.workers, thread_name_prefix="job")
        self.in_flight: set[int] = set()
        self.lock = threading.Lock()
        self.stop = threading.Event()
        self.seen: dict[Path, tuple[int, float]] = {}  # inbox file -> (size, mtime) last tick
        self.done: set[Path] = set()
        self.busy_assignments: set[str] = set()  # assignments with a rescan running

    def start(self):
        with session_scope() as db:  # anything "processing" was interrupted by a restart
            db.execute(update(Job).where(Job.state == "processing").values(state="queued"))
            db.execute(update(Submission).where(Submission.status == "processing").values(status="queued"))
        threading.Thread(target=self._loop, daemon=True, name="dispatcher").start()

    def _loop(self):
        while not self.stop.is_set():
            try:
                self._scan_inbox()
                self._dispatch()
            except Exception:
                log.exception("dispatcher tick failed")
            self.stop.wait(1.0)

    def _dispatch(self):
        with session_scope() as db:
            queued = db.scalars(select(Job.submission_id).where(Job.state == "queued").order_by(Job.id)).all()
        for sid in queued:
            with self.lock:
                if sid in self.in_flight or len(self.in_flight) >= get_settings().workers:
                    continue
                self.in_flight.add(sid)
            self.pool.submit(self._run, sid)

    def _run(self, sid: int):
        try:
            run_job(sid)
        except Exception:
            pass  # run_job already stored the error on the job row
        finally:
            with self.lock:
                self.in_flight.discard(sid)

    def _scan_inbox(self):
        """inbox/<assignment>/*.pdf. A file is registered once its size stopped changing for one tick."""
        root = get_settings().inbox
        root.mkdir(parents=True, exist_ok=True)
        for f in root.glob("*/*.pdf"):
            if f in self.done:
                continue
            st = f.stat()
            sig = (st.st_size, st.st_mtime)
            if self.seen.get(f) == sig:
                register(f, f.parent.name)
                self.done.add(f)
            self.seen[f] = sig

    def rescan_async(self, assignment: str):
        if assignment in self.busy_assignments:
            return

        def go():
            try:
                rescan(assignment)
            except Exception:
                log.exception("rescan of %s failed", assignment)
            finally:
                self.busy_assignments.discard(assignment)

        self.busy_assignments.add(assignment)
        threading.Thread(target=go, daemon=True, name=f"rescan-{assignment}").start()
