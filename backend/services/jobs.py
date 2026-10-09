"""
A small, bounded, in-process job runner.

Why in-process and bounded: this is a single-instance deployment, so a thread pool with a fixed number of
workers is enough to (a) return the upload request immediately, (b) cap how many analyses use the CPU at once,
and (c) avoid running Redis/Celery that we could neither test nor explain in one day.
Trade-off: jobs live in this process. A restart interrupts them (startup marks them failed so nobody is
blocked), and a second application instance would not share the queue. A durable queue (RQ/Celery + Redis)
is the next step once jobs must survive restarts or run across several instances.
"""
import logging
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any, Callable, Optional

from backend.core.logging import log_event

logger = logging.getLogger("finsight.jobs")


class JobRunner:
    def __init__(self, workers: int):
        if workers < 1:
            raise ValueError("workers must be at least 1")
        self.workers = workers
        self._executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="analysis")
        self._closed = False

    @property
    def is_running(self) -> bool:
        return not self._closed

    def submit(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Optional[Future]:
        if self._closed:
            raise RuntimeError("job runner is shut down")
        return self._executor.submit(self._guarded, fn, *args, **kwargs)

    @staticmethod
    def _guarded(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
        # A job must never take its worker thread down; failures are recorded by the job itself.
        try:
            fn(*args, **kwargs)
        except Exception:
            log_event(logger, logging.ERROR, "job_crashed", exc_info=True)

    def shutdown(self) -> None:
        """Stop accepting work, cancel jobs that have not started, and wait for the ones already running."""
        self._closed = True
        self._executor.shutdown(wait=True, cancel_futures=True)


class SyncJobRunner:
    """Runs jobs immediately in the calling thread. Used by tests so results are deterministic."""

    workers = 1
    is_running = True

    def submit(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
        JobRunner._guarded(fn, *args, **kwargs)

    def shutdown(self) -> None:
        self.is_running = False
