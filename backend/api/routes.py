"""
Upload, analysis-result and transaction endpoints. Every route requires a logged-in user, and every
database lookup includes that user's id.
"""
import hashlib
import logging
import uuid

import pandas as pd
from fastapi import APIRouter, BackgroundTasks, Depends, File, Query, UploadFile
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.api.deps import get_current_user_id
from backend.api.errors import AppError
from backend.api.schemas import (
    ResultOut,
    TransactionOut,
    TransactionsPage,
    UploadAccepted,
    UploadOut,
    UploadStatusOut,
)
from backend.core import repository as repo
from backend.core.config import settings
from backend.core.database import SessionLocal, get_db
from backend.core.models import Upload
from backend.ml.pipeline import run_full_pipeline
from backend.utils.csv_ingest import sanitize_filename, validate_and_clean_csv

logger = logging.getLogger("finsight.api")

router = APIRouter(prefix="/api", tags=["finance"])


def _run_pipeline_background(user_id: uuid.UUID, upload_id: uuid.UUID, df: pd.DataFrame):
    """Run the ML pipeline in the background. Failures are logged here and summarized safely for the user."""
    db = SessionLocal()
    try:
        results = run_full_pipeline(df)

        processed_df = results.pop("processed_df", df)
        repo.store_transactions(db, user_id, upload_id, processed_df)

        for module_name, module_data in results.get("modules", {}).items():
            repo.upsert_analysis_result(db, user_id, upload_id, module_name, module_data)

        if results.get("errors"):
            repo.upsert_analysis_result(db, user_id, upload_id, "errors", {"errors": results["errors"]})

        if results.get("status") == "failed":
            repo.update_upload_status(db, user_id, upload_id, "failed", error_summary="Analysis failed.")
        else:
            repo.update_upload_status(db, user_id, upload_id, "completed")
    except Exception:
        logger.exception("pipeline_failed upload_id=%s", upload_id)
        db.rollback()
        repo.update_upload_status(db, user_id, upload_id, "failed", error_summary="Analysis failed.")
    finally:
        db.close()


def _upload_not_found() -> AppError:
    # Identical for "does not exist" and "belongs to someone else", so ids cannot be probed.
    return AppError(404, "NOT_FOUND", "Upload not found.")


def _owned_upload(db: Session, user_id: uuid.UUID, upload_id: uuid.UUID) -> Upload:
    upload = repo.get_upload(db, user_id, upload_id)
    if upload is None:
        raise _upload_not_found()
    return upload


@router.post("/uploads", response_model=UploadAccepted, status_code=202)
def create_upload(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    amount_convention: str = Query("auto", description="auto | expenses_positive | expenses_negative"),
    db: Session = Depends(get_db),
    user_id: uuid.UUID = Depends(get_current_user_id),
):
    """Validate a CSV, record it, and start the analysis in the background."""
    filename = sanitize_filename(file.filename)
    # Read at most one byte past the limit so an oversized upload is never fully loaded into memory.
    contents = file.file.read(settings.max_upload_bytes + 1)

    ingest = validate_and_clean_csv(
        contents,
        filename,
        amount_convention,
        max_bytes=settings.max_upload_bytes,
        max_rows=settings.max_upload_rows,
        max_invalid_share=settings.max_invalid_row_share,
    )

    active_error = AppError(
        409, "ACTIVE_JOB_EXISTS", "You already have an analysis running. Please wait for it to finish."
    )
    if repo.has_active_upload(db, user_id):
        raise active_error
    try:
        upload = repo.create_upload(db, user_id, filename, hashlib.sha256(contents).hexdigest(), len(ingest.df))
    except IntegrityError:  # the database's one-active-upload rule caught a simultaneous request
        db.rollback()
        raise active_error
    repo.update_upload_status(db, user_id, upload.id, "processing")

    background_tasks.add_task(_run_pipeline_background, user_id, upload.id, ingest.df)

    return UploadAccepted(
        upload_id=upload.id,
        filename=filename,
        status="processing",
        rows_received=ingest.rows_received,
        rows_dropped=ingest.rows_dropped,
        amount_convention=ingest.amount_convention,
        message="File accepted. Analysis is running in the background.",
    )


def _upload_out(u: Upload) -> UploadOut:
    return UploadOut(
        id=u.id,
        filename=u.original_filename,
        row_count=u.row_count,
        status=u.status,
        error_summary=u.error_summary,
        created_at=u.created_at,
        completed_at=u.completed_at,
    )


@router.get("/uploads", response_model=list[UploadOut])
def list_uploads(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    user_id: uuid.UUID = Depends(get_current_user_id),
):
    return [_upload_out(u) for u in repo.list_uploads(db, user_id, limit=limit, offset=offset)]


@router.get("/uploads/{upload_id}", response_model=UploadOut)
def get_upload(upload_id: uuid.UUID, db: Session = Depends(get_db), user_id: uuid.UUID = Depends(get_current_user_id)):
    return _upload_out(_owned_upload(db, user_id, upload_id))


@router.get("/uploads/{upload_id}/status", response_model=UploadStatusOut)
def get_upload_status(
    upload_id: uuid.UUID, db: Session = Depends(get_db), user_id: uuid.UUID = Depends(get_current_user_id)
):
    upload = _owned_upload(db, user_id, upload_id)
    return UploadStatusOut(upload_id=upload.id, status=upload.status, error_summary=upload.error_summary)


def _result(db: Session, user_id: uuid.UUID, upload_id: uuid.UUID, stored_type: str, public_type: str) -> ResultOut:
    _owned_upload(db, user_id, upload_id)
    payload = repo.get_analysis_result(db, user_id, upload_id, stored_type)
    if payload is None:
        raise AppError(404, "RESULT_NOT_AVAILABLE", f"No {public_type} result is available for this upload.")
    return ResultOut(result_type=public_type, data=payload)


@router.get("/uploads/{upload_id}/summary", response_model=ResultOut)
def get_summary(upload_id: uuid.UUID, db: Session = Depends(get_db), user_id: uuid.UUID = Depends(get_current_user_id)):
    return _result(db, user_id, upload_id, "summary", "summary")


@router.get("/uploads/{upload_id}/forecast", response_model=ResultOut)
def get_forecast(upload_id: uuid.UUID, db: Session = Depends(get_db), user_id: uuid.UUID = Depends(get_current_user_id)):
    return _result(db, user_id, upload_id, "prediction", "forecast")


@router.get("/uploads/{upload_id}/anomalies", response_model=ResultOut)
def get_anomalies(upload_id: uuid.UUID, db: Session = Depends(get_db), user_id: uuid.UUID = Depends(get_current_user_id)):
    return _result(db, user_id, upload_id, "anomaly", "anomalies")


@router.get("/uploads/{upload_id}/transactions", response_model=TransactionsPage)
def get_upload_transactions(
    upload_id: uuid.UUID,
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    user_id: uuid.UUID = Depends(get_current_user_id),
):
    _owned_upload(db, user_id, upload_id)
    rows = repo.get_transactions(db, user_id, upload_id, limit=limit, offset=offset)
    return TransactionsPage(
        upload_id=upload_id,
        count=len(rows),
        limit=limit,
        offset=offset,
        transactions=[
            TransactionOut(
                id=t.id,
                date=t.transaction_date.isoformat() if t.transaction_date else None,
                amount=float(t.amount),
                category=t.confirmed_category or t.source_category or t.predicted_category or "Uncategorized",
                description=t.description,
                predicted_category=t.predicted_category,
                anomaly_score=t.anomaly_score,
                anomaly_rank=t.anomaly_rank,
            )
            for t in rows
        ],
    )


@router.delete("/uploads/{upload_id}", status_code=204)
def delete_upload(upload_id: uuid.UUID, db: Session = Depends(get_db), user_id: uuid.UUID = Depends(get_current_user_id)):
    if not repo.delete_upload(db, user_id, upload_id):
        raise _upload_not_found()
