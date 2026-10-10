"""
Upload, analysis-result and transaction endpoints. Every route requires a logged-in user, and every
database lookup includes that user's id.
"""
import hashlib
import logging
import uuid

from fastapi import APIRouter, Depends, File, Path, Query, Request, Response, UploadFile
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.api.deps import get_current_user_id
from backend.api.errors import AppError
from backend.api.schemas import (
    AnomaliesOut,
    AnomalyReviewUpdate,
    BudgetIn,
    BudgetOut,
    CategoryUpdate,
    ModuleStatusOut,
    ResultOut,
    TransactionOut,
    TransactionsPage,
    UnusualTransaction,
    UploadAccepted,
    UploadOut,
    UploadStatusOut,
)
from backend.core import repository as repo
from backend.core.config import settings
from backend.core.database import get_db
from backend.core.logging import log_event, request_id_var
from backend.core.models import Upload
from backend.ml.anomaly import DISCLAIMER as ANOMALY_DISCLAIMER
from backend.services.anomaly_refresh import refresh_anomaly_ranking
from backend.services.budget_risk import compute_budget_risk
from backend.services.job_input import encode_input
from backend.utils.csv_ingest import sanitize_filename, validate_and_clean_csv
from backend.utils.helpers import calculate_summary_stats

logger = logging.getLogger("finsight.api")

router = APIRouter(prefix="/api", tags=["finance"])


def get_categorizer(request: Request):
    """The categorizer loaded at startup; uploads are refused while it is unavailable."""
    categorizer = getattr(request.app.state, "categorizer", None)
    if categorizer is None:
        raise AppError(503, "MODEL_UNAVAILABLE", "The categorization model is unavailable. Please try again later.")
    return categorizer


def get_job_runner(request: Request):
    runner = getattr(request.app.state, "job_runner", None)
    if runner is None or not runner.is_running:
        raise AppError(503, "NOT_READY", "The analysis service is not available. Please try again shortly.")
    return runner


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
    response: Response,
    file: UploadFile = File(...),
    amount_convention: str = Query("auto", description="auto | expenses_positive | expenses_negative"),
    db: Session = Depends(get_db),
    user_id: uuid.UUID = Depends(get_current_user_id),
    categorizer=Depends(get_categorizer),
    runner=Depends(get_job_runner),
):
    """Validate a CSV and queue its analysis, or return your existing analysis of the same file."""
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
    content_sha256 = hashlib.sha256(contents).hexdigest()

    # Same user + same file + same sign convention + same model version => the analysis would be identical.
    # The lookup is scoped to this user, so one person's upload can never be returned to another.
    existing = repo.find_reusable_upload(db, user_id, content_sha256, ingest.amount_convention)
    if existing is not None:
        cached = repo.get_analysis_result(db, user_id, existing.id, "categorization")
        if cached and cached.get("model_version") == categorizer.version:
            log_event(logger, logging.INFO, "upload_reused", upload_id=str(existing.id), user_id=str(user_id))
            response.status_code = 200
            return UploadAccepted(
                upload_id=existing.id,
                filename=existing.original_filename,
                status=existing.status,
                reused=True,
                rows_received=ingest.rows_received,
                rows_dropped=ingest.rows_dropped,
                amount_convention=ingest.amount_convention,
                message="You already analysed this exact file, so that analysis is shown. "
                "Delete it first if you want a fresh one.",
            )

    if repo.count_active_uploads(db) >= settings.max_active_jobs:
        raise AppError(503, "SERVER_BUSY", "The server is busy analysing other uploads. Please try again in a minute.")
    active_error = AppError(
        409, "ACTIVE_JOB_EXISTS", "You already have an analysis running. Please wait for it to finish."
    )
    if repo.has_active_upload(db, user_id):
        raise active_error
    try:
        # The upload, its pending module runs and its input are saved together: this row IS the queued job.
        upload = repo.enqueue_upload(
            db, user_id, filename, content_sha256, len(ingest.df), ingest.amount_convention,
            encode_input(ingest.df), request_id_var.get(),
        )
    except IntegrityError:  # the database's one-active-upload rule caught a simultaneous request
        db.rollback()
        raise active_error

    log_event(
        logger, logging.INFO, "upload_accepted",
        upload_id=str(upload.id), user_id=str(user_id), rows=len(ingest.df), rows_dropped=ingest.rows_dropped,
        amount_convention=ingest.amount_convention,
    )
    runner.wake()  # an idle worker (in this or another instance) picks the job up from the database

    return UploadAccepted(
        upload_id=upload.id,
        filename=filename,
        status="queued",
        rows_received=ingest.rows_received,
        rows_dropped=ingest.rows_dropped,
        amount_convention=ingest.amount_convention,
        message="File accepted. Analysis is queued.",
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


@router.get("/categories")
def list_categories(user_id: uuid.UUID = Depends(get_current_user_id), categorizer=Depends(get_categorizer)):
    """The categories the app can assign, for the category-correction dropdown."""
    return {"categories": categorizer.categories, "model_version": categorizer.version}


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
    runs = repo.list_runs(db, user_id, upload_id)
    return UploadStatusOut(
        upload_id=upload.id,
        status=upload.status,
        error_summary=upload.error_summary,
        modules=[
            ModuleStatusOut(
                module=r.module, status=r.status, duration_ms=r.duration_ms, model_version=r.model_version,
                error_code=r.error_code, error_message=r.error_message, started_at=r.started_at, finished_at=r.finished_at,
            )
            for r in runs
        ],
    )


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
    return _result(db, user_id, upload_id, "forecast", "forecast")


@router.get("/uploads/{upload_id}/anomalies", response_model=AnomaliesOut)
def get_anomalies(upload_id: uuid.UUID, db: Session = Depends(get_db), user_id: uuid.UUID = Depends(get_current_user_id)):
    """The unusual-transaction review queue: ranked candidates and your confirm/dismiss decisions."""
    _owned_upload(db, user_id, upload_id)
    summary = repo.get_analysis_result(db, user_id, upload_id, "anomaly")
    if summary is None:
        return AnomaliesOut(
            status="not_available",
            reason="No unusual-transaction result is available for this upload.",
            disclaimer=ANOMALY_DISCLAIMER,
        )
    queue = repo.get_review_queue(db, user_id, upload_id)
    items = [
        UnusualTransaction(
            transaction_id=t.id,
            rank=t.anomaly_rank,
            date=t.transaction_date.isoformat() if t.transaction_date else None,
            description=t.description,
            amount=float(t.amount),
            category=repo.effective_category(t),
            score=t.anomaly_score,
            reason=t.anomaly_reason,
            review_status=t.anomaly_review_status,
        )
        for t in queue
    ]
    return AnomaliesOut(
        status=summary["status"],
        reason=summary.get("reason"),
        method=summary.get("method"),
        review_capacity=summary.get("review_capacity"),
        expenses_scanned=summary.get("expenses_scanned"),
        reviewed=sum(i.review_status != "unreviewed" for i in items),
        confirmed=sum(i.review_status == "confirmed" for i in items),
        decisions_outside_queue=repo.count_decisions_outside_queue(db, user_id, upload_id),
        dismissed=sum(i.review_status == "dismissed" for i in items),
        items=items,
        disclaimer=summary.get("disclaimer", ANOMALY_DISCLAIMER),
    )


@router.get("/uploads/{upload_id}/transactions", response_model=TransactionsPage)
def get_upload_transactions(
    upload_id: uuid.UUID,
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    review_required: bool | None = Query(None, description="true: only rows needing a category; false: only categorized rows"),
    db: Session = Depends(get_db),
    user_id: uuid.UUID = Depends(get_current_user_id),
):
    _owned_upload(db, user_id, upload_id)
    rows = repo.get_transactions(db, user_id, upload_id, limit=limit, offset=offset, review_required=review_required)
    return TransactionsPage(
        upload_id=upload_id,
        count=len(rows),
        limit=limit,
        offset=offset,
        transactions=[_transaction_out(t) for t in rows],
    )


def _transaction_out(t) -> TransactionOut:
    category = repo.effective_category(t)
    return TransactionOut(
        id=t.id,
        date=t.transaction_date.isoformat() if t.transaction_date else None,
        amount=float(t.amount),
        category=category,
        description=t.description,
        source_category=t.source_category,
        predicted_category=t.predicted_category,
        prediction_confidence=t.prediction_confidence,
        confirmed_category=t.confirmed_category,
        review_required=category == "Uncategorized",
        anomaly_score=t.anomaly_score,
        anomaly_rank=t.anomaly_rank,
        anomaly_reason=t.anomaly_reason,
        anomaly_review_status=t.anomaly_review_status,
    )


@router.patch("/transactions/{transaction_id}/category", response_model=TransactionOut)
def correct_transaction_category(
    transaction_id: int,
    body: CategoryUpdate,
    db: Session = Depends(get_db),
    user_id: uuid.UUID = Depends(get_current_user_id),
):
    """Set your own category for a transaction. It overrides the model's prediction in every summary."""
    category = " ".join(body.category.split())
    if not category:
        raise AppError(422, "VALIDATION_ERROR", "Category cannot be blank.")
    existing = repo.get_owned_transaction(db, user_id, transaction_id)
    if existing is None:
        raise AppError(404, "NOT_FOUND", "Transaction not found.")
    before = repo.effective_category(existing)
    txn = repo.set_confirmed_category(db, user_id, transaction_id, category)
    if repo.effective_category(txn) != before:
        # The unusual-transaction ranking compares each expense with its category, so it must be recomputed.
        refresh_anomaly_ranking(db, user_id, txn.upload_id)
    # Rebuild the stored summary so charts, totals and the review-queue size use the corrected data.
    frame = repo.transactions_dataframe(db, user_id, txn.upload_id)
    repo.upsert_analysis_result(db, user_id, txn.upload_id, "summary", calculate_summary_stats(frame))
    return _transaction_out(txn)


@router.delete("/uploads/{upload_id}", status_code=204)
def delete_upload(upload_id: uuid.UUID, db: Session = Depends(get_db), user_id: uuid.UUID = Depends(get_current_user_id)):
    if not repo.delete_upload(db, user_id, upload_id):
        raise _upload_not_found()


@router.patch("/transactions/{transaction_id}/anomaly-review", response_model=TransactionOut)
def review_unusual_transaction(
    transaction_id: int,
    body: AnomalyReviewUpdate,
    db: Session = Depends(get_db),
    user_id: uuid.UUID = Depends(get_current_user_id),
):
    """Confirm (worth following up) or dismiss (expected) a transaction in the review queue."""
    txn = repo.get_owned_transaction(db, user_id, transaction_id)
    if txn is None:
        raise AppError(404, "NOT_FOUND", "Transaction not found.")
    if txn.anomaly_rank is None:
        raise AppError(422, "NOT_IN_REVIEW_QUEUE", "This transaction is not in the unusual-transaction review queue.")
    return _transaction_out(repo.set_anomaly_review(db, user_id, transaction_id, body.status))


@router.get("/uploads/{upload_id}/budget-risk")
def get_budget_risk(upload_id: uuid.UUID, db: Session = Depends(get_db), user_id: uuid.UUID = Depends(get_current_user_id)):
    """Current and projected month-end spending against your budgets, using each transaction's effective category."""
    _owned_upload(db, user_id, upload_id)
    budgets = {b.category: float(b.monthly_limit) for b in repo.list_budgets(db, user_id)}
    transactions = repo.transactions_dataframe(db, user_id, upload_id)
    forecast = repo.get_analysis_result(db, user_id, upload_id, "forecast")
    return compute_budget_risk(transactions, budgets, forecast)


def _budget_out(b) -> BudgetOut:
    return BudgetOut(
        category=b.category, monthly_limit=float(b.monthly_limit), created_at=b.created_at, updated_at=b.updated_at
    )


def _clean_budget_category(category: str) -> str:
    cleaned = " ".join(category.split())
    if not cleaned or len(cleaned) > 100:
        raise AppError(422, "VALIDATION_ERROR", "Category must be between 1 and 100 characters.")
    return cleaned


@router.get("/budgets", response_model=list[BudgetOut])
def list_budgets(db: Session = Depends(get_db), user_id: uuid.UUID = Depends(get_current_user_id)):
    return [_budget_out(b) for b in repo.list_budgets(db, user_id)]


@router.put("/budgets/{category}", response_model=BudgetOut)
def put_budget(
    body: BudgetIn,
    category: str = Path(min_length=1, max_length=200),
    db: Session = Depends(get_db),
    user_id: uuid.UUID = Depends(get_current_user_id),
):
    """Create or replace the monthly limit for one category."""
    return _budget_out(repo.upsert_budget(db, user_id, _clean_budget_category(category), body.monthly_limit))


@router.delete("/budgets/{category}", status_code=204)
def remove_budget(
    category: str = Path(min_length=1, max_length=200),
    db: Session = Depends(get_db),
    user_id: uuid.UUID = Depends(get_current_user_id),
):
    if not repo.delete_budget(db, user_id, _clean_budget_category(category)):
        raise AppError(404, "NOT_FOUND", "Budget not found.")
