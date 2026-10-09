"""
The analysis job: runs the pipeline for one upload and records exactly what happened.

State is written to the database before work starts (upload `queued`, one `pending` run per module) and
updated as each module starts and finishes, so the status endpoint always reflects reality and a crash
or restart leaves an explainable trail instead of an upload that looks busy forever.
"""
import logging
import time
import uuid
from typing import Callable, Optional

import pandas as pd
from sqlalchemy.orm import Session

from backend.core import repository as repo
from backend.core.logging import log_event, request_id_var
from backend.ml.pipeline import ModuleOutcome, run_full_pipeline

logger = logging.getLogger("finsight.jobs")


class RunRecorder:
    """Pipeline observer that persists each module's progress. Modules may report from different threads, so
    every event uses its own short-lived database session."""

    def __init__(self, session_factory: Callable[[], Session], user_id: uuid.UUID, upload_id: uuid.UUID):
        self.session_factory, self.user_id, self.upload_id = session_factory, user_id, upload_id

    def on_start(self, module: str) -> None:
        with self.session_factory() as db:
            repo.start_run(db, self.user_id, self.upload_id, module)

    def on_finish(self, module: str, outcome: ModuleOutcome, duration_ms: int) -> None:
        with self.session_factory() as db:
            repo.finish_run(
                db, self.user_id, self.upload_id, module, outcome.status, duration_ms,
                outcome.model_version, outcome.error_code, outcome.error_message,
            )
        log_event(
            logger,
            logging.WARNING if outcome.status == "failed" else logging.INFO,
            "module_finished",
            upload_id=str(self.upload_id),
            module=module,
            status=outcome.status,
            duration_ms=duration_ms,
            model_version=outcome.model_version,
            error_code=outcome.error_code,
        )


def overall_status(runs) -> str:
    """completed: nothing failed. partial: something failed but something useful finished. failed: nothing useful."""
    failed = [r for r in runs if r.status == "failed"]
    if not failed:
        return "completed"
    return "partial" if any(r.status == "completed" for r in runs) else "failed"


def run_analysis_job(
    session_factory: Callable[[], Session],
    user_id: uuid.UUID,
    upload_id: uuid.UUID,
    df: pd.DataFrame,
    categorizer,
    request_id: Optional[str] = None,
) -> None:
    request_id_var.set(request_id)  # tie this background work to the request that started it
    started = time.perf_counter()
    upload_ref = str(upload_id)
    db = session_factory()
    try:
        repo.update_upload_status(db, user_id, upload_id, "processing")
        log_event(logger, logging.INFO, "job_started", upload_id=upload_ref, rows=len(df))

        results = run_full_pipeline(df, categorizer, observer=RunRecorder(session_factory, user_id, upload_id))

        if results["status"] == "failed":
            repo.close_open_runs(db, user_id, upload_id, "skipped", "PREPROCESSING_FAILED", "The file could not be prepared.")
            repo.update_upload_status(db, user_id, upload_id, "failed", error_summary="The file could not be processed.")
            status, failed_modules = "failed", ["preprocessing"]
        else:
            repo.store_transactions(db, user_id, upload_id, results["processed_df"])
            for name, payload in results["modules"].items():
                repo.upsert_analysis_result(db, user_id, upload_id, name, payload)
            runs = repo.list_runs(db, user_id, upload_id)
            status = overall_status(runs)
            failed_modules = [r.module for r in runs if r.status == "failed"]
            summary = None if status == "completed" else (
                "Some analysis steps failed: " + ", ".join(failed_modules) + "."
                if status == "partial" else "Analysis failed."
            )
            repo.update_upload_status(db, user_id, upload_id, status, error_summary=summary)

        modules = results.get("modules", {})
        log_event(
            logger,
            logging.INFO if status != "failed" else logging.ERROR,
            "job_finished",
            upload_id=upload_ref,
            status=status,
            duration_ms=int((time.perf_counter() - started) * 1000),
            failed_modules=",".join(failed_modules),
            auto_categorized=modules.get("categorization", {}).get("auto_categorized"),
            needs_review=modules.get("categorization", {}).get("needs_review"),
            forecast_method=modules.get("forecast", {}).get("method"),
            review_queue_size=modules.get("summary", {}).get("review_queue_size"),
        )
    except LookupError:
        # The user deleted the upload while it was being analysed; there is nothing left to record.
        db.rollback()
        log_event(logger, logging.INFO, "job_abandoned_upload_deleted", upload_id=upload_ref)
    except Exception:
        log_event(logger, logging.ERROR, "job_crashed", upload_id=upload_ref, exc_info=True)
        db.rollback()
        try:
            repo.close_open_runs(db, user_id, upload_id, "failed", "JOB_CRASHED", "Analysis failed unexpectedly.")
            repo.update_upload_status(db, user_id, upload_id, "failed", error_summary="Analysis failed.")
        except Exception:
            log_event(logger, logging.ERROR, "job_failure_not_recorded", upload_id=upload_ref, exc_info=True)
    finally:
        db.close()
