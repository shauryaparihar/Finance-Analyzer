"""
Data-access functions. Every function that touches user-owned data takes the user's id and
applies it inside the SQL query, so another user's rows can never be returned or changed.
"""
import uuid
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Optional

import pandas as pd
from sqlalchemy import and_, delete, func, insert, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from backend.core.models import MODULES, AnalysisResult, AnalysisRun, Budget, Transaction, Upload, User
from backend.utils.helpers import safe_json_serializable

TERMINAL_UPLOAD_STATUSES = {"completed", "partial", "failed"}
# An upload only moves forward: queued -> processing -> completed | partial | failed (queued may also fail directly).
ALLOWED_TRANSITIONS = {
    "queued": {"processing", "failed"},
    "processing": {"completed", "partial", "failed"},
    "completed": set(),
    "partial": set(),
    "failed": set(),
}


class InvalidStatusTransition(ValueError):
    pass
ACTIVE_UPLOAD_STATUSES = ("queued", "processing")


def _money(value: Any) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _clean(value: Any) -> Any:
    """Turn pandas missing values (NaN/NaT/None) into None."""
    return None if pd.isna(value) else value


# --- users ---

def create_user(db: Session, email: str, password_hash: str) -> User:
    user = User(email=email.strip().lower(), password_hash=password_hash)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def get_user(db: Session, user_id: uuid.UUID) -> Optional[User]:
    return db.get(User, user_id)


def get_user_by_email(db: Session, email: str) -> Optional[User]:
    return db.scalar(select(User).where(User.email == email.strip().lower()))


# --- uploads ---

def create_upload(
    db: Session,
    user_id: uuid.UUID,
    filename: str,
    content_sha256: str,
    row_count: int,
    amount_convention: Optional[str] = None,
) -> Upload:
    upload = Upload(
        user_id=user_id,
        original_filename=filename,
        content_sha256=content_sha256,
        row_count=row_count,
        amount_convention=amount_convention,
    )
    db.add(upload)
    db.commit()
    db.refresh(upload)
    return upload


def get_upload(db: Session, user_id: uuid.UUID, upload_id: uuid.UUID) -> Optional[Upload]:
    return db.scalar(select(Upload).where(Upload.id == upload_id, Upload.user_id == user_id))


def list_uploads(db: Session, user_id: uuid.UUID, limit: int = 50, offset: int = 0) -> list[Upload]:
    stmt = (
        select(Upload).where(Upload.user_id == user_id).order_by(Upload.created_at.desc()).limit(limit).offset(offset)
    )
    return list(db.scalars(stmt))


def update_upload_status(
    db: Session, user_id: uuid.UUID, upload_id: uuid.UUID, status: str, error_summary: Optional[str] = None
) -> bool:
    upload = get_upload(db, user_id, upload_id)
    if upload is None:
        return False
    if status not in ALLOWED_TRANSITIONS.get(upload.status, set()):
        raise InvalidStatusTransition(f"{upload.status} -> {status}")
    upload.status = status
    upload.error_summary = error_summary
    if status in TERMINAL_UPLOAD_STATUSES:
        upload.completed_at = datetime.now(timezone.utc)
    db.commit()
    return True


def delete_upload(db: Session, user_id: uuid.UUID, upload_id: uuid.UUID) -> bool:
    """Delete an upload owned by user_id. Dependent rows are removed by the database (ON DELETE CASCADE)."""
    result = db.execute(delete(Upload).where(Upload.id == upload_id, Upload.user_id == user_id))
    db.commit()
    return result.rowcount > 0


# --- transactions ---

def store_transactions(db: Session, user_id: uuid.UUID, upload_id: uuid.UUID, df: pd.DataFrame) -> int:
    """Bulk-insert processed transactions into an upload owned by user_id."""
    if get_upload(db, user_id, upload_id) is None:
        raise LookupError("Upload not found")

    rows = []
    for _, row in df.iterrows():
        txn_date = _clean(row.get("date"))
        category = _clean(row.get("category"))
        description = _clean(row.get("description"))
        score = _clean(row.get("anomaly_score"))
        rows.append(
            {
                "upload_id": upload_id,
                "transaction_date": txn_date.date() if txn_date is not None else None,
                "amount": _money(row["amount"]),
                "description": str(description)[:500] if description is not None else None,
                "source_category": None if category in (None, "Uncategorized") else str(category)[:100],
                "predicted_category": _clean(row.get("predicted_category")),
                "prediction_confidence": float(row["prediction_confidence"])
                if _clean(row.get("prediction_confidence")) is not None
                else None,
                "anomaly_score": float(score) if score is not None else None,
                "anomaly_rank": int(row["anomaly_rank"]) if _clean(row.get("anomaly_rank")) is not None else None,
                "anomaly_reason": _clean(row.get("anomaly_reason")),
            }
        )
    if rows:
        db.execute(insert(Transaction), rows)
    db.commit()
    return len(rows)


def _needs_review():
    """No confirmed, source or confident predicted category: the effective category is Uncategorized."""
    return and_(
        Transaction.confirmed_category.is_(None),
        Transaction.source_category.is_(None),
        or_(Transaction.predicted_category.is_(None), Transaction.predicted_category == "Uncategorized"),
    )


def get_transactions(
    db: Session,
    user_id: uuid.UUID,
    upload_id: uuid.UUID,
    limit: int = 100,
    offset: int = 0,
    review_required: Optional[bool] = None,
) -> list[Transaction]:
    stmt = (
        select(Transaction)
        .join(Upload, Upload.id == Transaction.upload_id)
        .where(Upload.id == upload_id, Upload.user_id == user_id)
    )
    if review_required is True:
        stmt = stmt.where(_needs_review())
    elif review_required is False:
        stmt = stmt.where(~_needs_review())
    stmt = stmt.order_by(Transaction.transaction_date, Transaction.id).limit(limit).offset(offset)
    return list(db.scalars(stmt))


def set_confirmed_category(
    db: Session, user_id: uuid.UUID, transaction_id: int, category: Optional[str]
) -> Optional[Transaction]:
    """Record the user's own category for a transaction in an upload they own. Returns None if not found."""
    stmt = (
        select(Transaction)
        .join(Upload, Upload.id == Transaction.upload_id)
        .where(Transaction.id == transaction_id, Upload.user_id == user_id)
    )
    txn = db.scalar(stmt)
    if txn is None:
        return None
    txn.confirmed_category = category
    db.commit()
    db.refresh(txn)
    return txn


def effective_category(txn: Transaction) -> str:
    """confirmed -> source -> predicted -> Uncategorized"""
    return txn.confirmed_category or txn.source_category or txn.predicted_category or "Uncategorized"


def transactions_dataframe(db: Session, user_id: uuid.UUID, upload_id: uuid.UUID) -> pd.DataFrame:
    """All of an upload's transactions as a DataFrame with the effective category (used to rebuild summaries)."""
    stmt = (
        select(Transaction)
        .join(Upload, Upload.id == Transaction.upload_id)
        .where(Upload.id == upload_id, Upload.user_id == user_id)
        .order_by(Transaction.id)
    )
    rows = [
        {
            "id": t.id,
            "date": pd.Timestamp(t.transaction_date) if t.transaction_date else pd.NaT,
            "amount": float(t.amount),
            "description": t.description,
            "effective_category": effective_category(t),
            "is_anomaly": t.anomaly_rank is not None,
        }
        for t in db.scalars(stmt)
    ]
    return pd.DataFrame(rows, columns=["id", "date", "amount", "description", "effective_category", "is_anomaly"])


# --- analysis results ---

def upsert_analysis_result(
    db: Session,
    user_id: uuid.UUID,
    upload_id: uuid.UUID,
    result_type: str,
    payload: Any,
    model_version: Optional[str] = None,
) -> None:
    if model_version is None and isinstance(payload, dict):
        model_version = payload.get("model_version")
    if get_upload(db, user_id, upload_id) is None:
        raise LookupError("Upload not found")
    values = {
        "upload_id": upload_id,
        "result_type": result_type,
        "payload": safe_json_serializable(payload),
        "model_version": model_version,
    }
    stmt = pg_insert(AnalysisResult).values(**values)
    stmt = stmt.on_conflict_do_update(
        constraint="uq_analysis_results_upload_type",
        set_={"payload": stmt.excluded.payload, "model_version": stmt.excluded.model_version},
    )
    db.execute(stmt)
    db.commit()


def get_analysis_result(db: Session, user_id: uuid.UUID, upload_id: uuid.UUID, result_type: str) -> Optional[Any]:
    stmt = (
        select(AnalysisResult.payload)
        .join(Upload, Upload.id == AnalysisResult.upload_id)
        .where(Upload.id == upload_id, Upload.user_id == user_id, AnalysisResult.result_type == result_type)
    )
    return db.scalar(stmt)


# --- budgets ---

def list_budgets(db: Session, user_id: uuid.UUID) -> list[Budget]:
    return list(db.scalars(select(Budget).where(Budget.user_id == user_id).order_by(Budget.category)))


def upsert_budget(db: Session, user_id: uuid.UUID, category: str, monthly_limit: Decimal) -> Budget:
    stmt = pg_insert(Budget).values(user_id=user_id, category=category, monthly_limit=_money(monthly_limit))
    stmt = stmt.on_conflict_do_update(
        constraint="uq_budgets_user_category", set_={"monthly_limit": stmt.excluded.monthly_limit}
    ).returning(Budget)
    budget = db.scalars(stmt, execution_options={"populate_existing": True}).one()
    db.commit()
    return budget


def delete_budget(db: Session, user_id: uuid.UUID, category: str) -> bool:
    result = db.execute(delete(Budget).where(Budget.user_id == user_id, Budget.category == category))
    db.commit()
    return result.rowcount > 0


# --- active jobs ---

def has_active_upload(db: Session, user_id: uuid.UUID) -> bool:
    stmt = select(Upload.id).where(Upload.user_id == user_id, Upload.status.in_(ACTIVE_UPLOAD_STATUSES)).limit(1)
    return db.scalar(stmt) is not None


def fail_stale_uploads(db: Session, reason: str = "Analysis was interrupted by a server restart.") -> int:
    """Mark uploads left queued/processing as failed, and close their open module runs, so users are never
    blocked by (or shown) a job that is no longer running. Only valid while a single application instance runs."""
    stale_ids = list(db.scalars(select(Upload.id).where(Upload.status.in_(ACTIVE_UPLOAD_STATUSES))))
    if not stale_ids:
        return 0
    now = datetime.now(timezone.utc)
    db.execute(
        update(Upload)
        .where(Upload.id.in_(stale_ids))
        .values(status="failed", error_summary=reason, completed_at=now)
    )
    db.execute(
        update(AnalysisRun)
        .where(AnalysisRun.upload_id.in_(stale_ids), AnalysisRun.status.in_(("pending", "running")))
        .values(status="failed", error_code="INTERRUPTED", error_message=reason, finished_at=now)
    )
    db.commit()
    return len(stale_ids)


def count_active_uploads(db: Session) -> int:
    """Queued + running analyses across all users (used to refuse new work when the server is saturated)."""
    return int(db.scalar(select(func.count()).select_from(Upload).where(Upload.status.in_(ACTIVE_UPLOAD_STATUSES))) or 0)


def find_reusable_upload(
    db: Session, user_id: uuid.UUID, content_sha256: str, amount_convention: str
) -> Optional[Upload]:
    """This user's newest completed upload of the same file analysed with the same sign convention."""
    stmt = (
        select(Upload)
        .where(
            Upload.user_id == user_id,
            Upload.content_sha256 == content_sha256,
            Upload.amount_convention == amount_convention,
            Upload.status == "completed",
        )
        .order_by(Upload.created_at.desc())
        .limit(1)
    )
    return db.scalar(stmt)


# --- per-module runs ---

def create_runs(db: Session, user_id: uuid.UUID, upload_id: uuid.UUID) -> None:
    """Persist one pending run per module before any work starts."""
    if get_upload(db, user_id, upload_id) is None:
        raise LookupError("Upload not found")
    db.execute(insert(AnalysisRun), [{"upload_id": upload_id, "module": m, "status": "pending"} for m in MODULES])
    db.commit()


def _owned_upload_ids(user_id: uuid.UUID, upload_id: uuid.UUID):
    return select(Upload.id).where(Upload.id == upload_id, Upload.user_id == user_id)


def start_run(db: Session, user_id: uuid.UUID, upload_id: uuid.UUID, module: str) -> None:
    db.execute(
        update(AnalysisRun)
        .where(AnalysisRun.upload_id.in_(_owned_upload_ids(user_id, upload_id)), AnalysisRun.module == module)
        .values(status="running", started_at=datetime.now(timezone.utc))
    )
    db.commit()


def finish_run(
    db: Session,
    user_id: uuid.UUID,
    upload_id: uuid.UUID,
    module: str,
    status: str,
    duration_ms: Optional[int] = None,
    model_version: Optional[str] = None,
    error_code: Optional[str] = None,
    error_message: Optional[str] = None,
) -> None:
    db.execute(
        update(AnalysisRun)
        .where(AnalysisRun.upload_id.in_(_owned_upload_ids(user_id, upload_id)), AnalysisRun.module == module)
        .values(
            status=status,
            duration_ms=duration_ms,
            model_version=model_version,
            error_code=error_code,
            error_message=error_message,
            finished_at=datetime.now(timezone.utc),
        )
    )
    db.commit()


def close_open_runs(
    db: Session, user_id: uuid.UUID, upload_id: uuid.UUID, status: str, error_code: str, error_message: str
) -> None:
    """Finish any run still pending/running (for example when preprocessing failed before they could start)."""
    db.execute(
        update(AnalysisRun)
        .where(
            AnalysisRun.upload_id.in_(_owned_upload_ids(user_id, upload_id)),
            AnalysisRun.status.in_(("pending", "running")),
        )
        .values(status=status, error_code=error_code, error_message=error_message, finished_at=datetime.now(timezone.utc))
    )
    db.commit()


def list_runs(db: Session, user_id: uuid.UUID, upload_id: uuid.UUID) -> list[AnalysisRun]:
    stmt = (
        select(AnalysisRun)
        .join(Upload, Upload.id == AnalysisRun.upload_id)
        .where(Upload.id == upload_id, Upload.user_id == user_id)
        .order_by(AnalysisRun.id)
    )
    return list(db.scalars(stmt))


# --- unusual-transaction review ---

def get_review_queue(db: Session, user_id: uuid.UUID, upload_id: uuid.UUID) -> list[Transaction]:
    """Transactions flagged for review, most unusual first."""
    stmt = (
        select(Transaction)
        .join(Upload, Upload.id == Transaction.upload_id)
        .where(Upload.id == upload_id, Upload.user_id == user_id, Transaction.anomaly_rank.is_not(None))
        .order_by(Transaction.anomaly_rank)
    )
    return list(db.scalars(stmt))


def get_owned_transaction(db: Session, user_id: uuid.UUID, transaction_id: int) -> Optional[Transaction]:
    stmt = (
        select(Transaction)
        .join(Upload, Upload.id == Transaction.upload_id)
        .where(Transaction.id == transaction_id, Upload.user_id == user_id)
    )
    return db.scalar(stmt)


def set_anomaly_review(db: Session, user_id: uuid.UUID, transaction_id: int, status: str) -> Optional[Transaction]:
    """Set confirmed/dismissed/unreviewed on a transaction the user owns. Returns None if not found."""
    stmt = (
        select(Transaction)
        .join(Upload, Upload.id == Transaction.upload_id)
        .where(Transaction.id == transaction_id, Upload.user_id == user_id)
    )
    txn = db.scalar(stmt)
    if txn is None:
        return None
    txn.anomaly_review_status = status
    db.commit()
    db.refresh(txn)
    return txn


def update_anomaly_columns(db: Session, user_id: uuid.UUID, upload_id: uuid.UUID, ranked: pd.DataFrame) -> None:
    """Overwrite score/rank/reason for the given transactions (index = transaction id) of an upload the user owns.
    Review decisions (confirmed/dismissed) are deliberately left untouched."""
    if get_upload(db, user_id, upload_id) is None:
        raise LookupError("Upload not found")
    rows = [
        {
            "id": int(txn_id),
            "anomaly_score": None if pd.isna(r["anomaly_score"]) else float(r["anomaly_score"]),
            "anomaly_rank": None if pd.isna(r["anomaly_rank"]) else int(r["anomaly_rank"]),
            "anomaly_reason": None if pd.isna(r["anomaly_reason"]) else str(r["anomaly_reason"]),
        }
        for txn_id, r in ranked.iterrows()
    ]
    if rows:
        db.execute(update(Transaction), rows)
    db.commit()


def count_decisions_outside_queue(db: Session, user_id: uuid.UUID, upload_id: uuid.UUID) -> int:
    """Confirm/dismiss decisions on transactions that are no longer in the review queue."""
    stmt = (
        select(func.count())
        .select_from(Transaction)
        .join(Upload, Upload.id == Transaction.upload_id)
        .where(
            Upload.id == upload_id,
            Upload.user_id == user_id,
            Transaction.anomaly_rank.is_(None),
            Transaction.anomaly_review_status != "unreviewed",
        )
    )
    return int(db.scalar(stmt) or 0)
