"""
A durable job queue that lives in PostgreSQL, with workers inside each application instance.

How it works
  * Queuing a job = inserting an upload row with status `queued` (plus its cleaned input). Nothing is held only
    in memory, so a restart cannot lose queued work.
  * Every instance runs a few worker threads. A worker claims the oldest queued job with
    `SELECT ... FOR UPDATE SKIP LOCKED`, so any number of instances share one queue and never take the same job.
  * While a job runs, a heartbeat refreshes `heartbeat_at`. If a worker dies, the heartbeat goes stale and any
    instance's reaper puts the job back in the queue (up to JOB_MAX_ATTEMPTS attempts). A live job is never
    touched by another instance, because its heartbeat is fresh.
  * Delivery is at-least-once: a job that was interrupted is run again. A retry first clears the previous
    attempt's output, and a worker that has lost its claim is fenced out of writing results.

What this does NOT give you (so Redis/Celery stay deferred, not rejected): workers poll the database (about
once a second), throughput is bounded by PostgreSQL, and there is no priority, scheduling or rate limiting.
A message broker becomes worth it when polling cost, latency or job volume starts to matter.
"""
import logging
import threading
import time
from typing import Callable, Optional

from sqlalchemy.orm import Session

from backend.core import repository as repo
from backend.core.logging import log_event

logger = logging.getLogger("finsight.jobs")


class Heartbeat:
    """Refreshes a running job's heartbeat from a background thread until stopped."""

    def __init__(self, session_factory: Callable[[], Session], upload_id, worker_id: str, interval: float):
        self._session_factory, self._upload_id, self._worker_id, self._interval = session_factory, upload_id, worker_id, interval
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="heartbeat", daemon=True)

    def _run(self) -> None:
        while not self._stop.wait(self._interval):
            try:
                with self._session_factory() as db:
                    if not repo.beat(db, self._upload_id, self._worker_id):
                        log_event(logger, logging.WARNING, "heartbeat_claim_lost", upload_id=str(self._upload_id))
                        return
            except Exception:
                log_event(logger, logging.ERROR, "heartbeat_failed", upload_id=str(self._upload_id), exc_info=True)

    def __enter__(self) -> "Heartbeat":
        self._thread.start()
        return self

    def __exit__(self, *exc) -> None:
        self._stop.set()
        self._thread.join(timeout=5)


class JobRunner:
    """Worker threads that drain the database queue. `process` runs one claimed job."""

    def __init__(
        self,
        session_factory: Callable[[], Session],
        process: Callable[..., None],
        is_ready: Callable[[], bool],
        instance_id: str,
        workers: int = 2,
        poll_seconds: float = 1.0,
        heartbeat_seconds: float = 10.0,
        stale_after_seconds: float = 60.0,
        max_attempts: int = 2,
    ):
        if workers < 1:
            raise ValueError("workers must be at least 1")
        self.session_factory, self.process, self.is_ready = session_factory, process, is_ready
        self.instance_id, self.workers = instance_id, workers
        self.poll_seconds, self.heartbeat_seconds = poll_seconds, heartbeat_seconds
        self.stale_after_seconds, self.max_attempts = stale_after_seconds, max_attempts
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._threads: list[threading.Thread] = []
        self._last_reap = 0.0
        self._reap_lock = threading.Lock()
        self._running = False

    @property
    def is_running(self) -> bool:
        return self._running and not self._stop.is_set()

    def start(self) -> None:
        self._running = True
        for index in range(self.workers):
            thread = threading.Thread(target=self._loop, args=(f"{self.instance_id}/w{index}",), name=f"worker-{index}", daemon=True)
            thread.start()
            self._threads.append(thread)

    def wake(self) -> None:
        """Tell idle workers there may be new work (other instances find it on their next poll)."""
        self._wake.set()

    def shutdown(self) -> None:
        """Stop claiming new jobs and wait for running ones. Queued jobs simply stay queued for the next worker."""
        self._stop.set()
        self._wake.set()
        for thread in self._threads:
            thread.join()
        self._running = False

    # --- internals ---

    def _loop(self, worker_id: str) -> None:
        while not self._stop.is_set():
            try:
                self.reap_if_due()
                if not self.run_one(worker_id):
                    self._wake.wait(self.poll_seconds)
                    self._wake.clear()
            except Exception:
                log_event(logger, logging.ERROR, "worker_loop_error", worker_id=worker_id, exc_info=True)
                self._stop.wait(self.poll_seconds)

    def reap_if_due(self, force: bool = False) -> dict:
        """Recover orphaned jobs at most every stale_after/4 seconds per instance."""
        with self._reap_lock:
            now = time.monotonic()
            if not force and now - self._last_reap < max(self.stale_after_seconds / 4, 0.01):
                return {"requeued": 0, "failed": 0}
            self._last_reap = now
        with self.session_factory() as db:
            outcome = repo.reap_orphaned_jobs(db, self.stale_after_seconds, self.max_attempts)
        if outcome["requeued"] or outcome["failed"]:
            log_event(logger, logging.WARNING, "orphaned_jobs_recovered", **outcome)
            self._wake.set()
        return outcome

    def run_one(self, worker_id: str) -> bool:
        """Claim and run one job if there is one and the service is ready. Returns whether a job was run."""
        if not self.is_ready():
            return False  # for example the categorizer is unavailable: leave the work queued
        with self.session_factory() as db:
            upload = repo.claim_next_job(db, worker_id)
            if upload is None:
                return False
            claim = {"user_id": upload.user_id, "upload_id": upload.id, "attempts": upload.attempts, "request_id": upload.request_id}
        with Heartbeat(self.session_factory, claim["upload_id"], worker_id, self.heartbeat_seconds):
            try:
                self.process(self.session_factory, worker_id=worker_id, **claim)
            except Exception:
                log_event(logger, logging.ERROR, "job_crashed", upload_id=str(claim["upload_id"]), exc_info=True)
        return True

    def drain(self, worker_id: Optional[str] = None) -> int:
        """Run queued jobs in the calling thread until none are left. Used by tests and one-off tooling."""
        count = 0
        while self.run_one(worker_id or f"{self.instance_id}/drain"):
            count += 1
        return count


class InlineJobRunner(JobRunner):
    """For tests: queued work is run immediately, in the caller's thread, when wake() is called."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._running = True

    def wake(self) -> None:
        self.drain()

    def shutdown(self) -> None:
        self._stop.set()
        self._running = False
