"""
Data-access functions. Every function that touches user-owned data takes the user's id and
applies it inside the SQL query, so another user's rows can never be returned or changed.
"""
import uuid
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Optional

import pandas as pd
from sqlalchemy import delete, insert, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from backend.core.models import AnalysisResult, Budget, Transaction, Upload, User
from backend.utils.helpers import safe_json_serializable

TERMINAL_UPLOAD_STATUSES = {"completed", "partial", "failed"}


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


def get_user_by_email(db: Session, email: str) -> Optional[User]:
    return db.scalar(select(User).where(User.email == email.strip().lower()))


# --- uploads ---

def create_upload(db: Session, user_id: uuid.UUID, filename: str, content_sha256: str, row_count: int) -> Upload:
    upload = Upload(user_id=user_id, original_filename=filename, content_sha256=content_sha256, row_count=row_count)
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

    ranks: dict[int, int] = {}
    if "is_anomaly" in df.columns and "anomaly_score" in df.columns:
        flagged = df[df["is_anomaly"].fillna(False).astype(bool)].sort_values("anomaly_score")
        ranks = {idx: n for n, idx in enumerate(flagged.index, start=1)}

    rows = []
    for idx, row in df.iterrows():
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
                "anomaly_score": float(score) if score is not None else None,
                "anomaly_rank": ranks.get(idx),
            }
        )
    if rows:
        db.execute(insert(Transaction), rows)
    db.commit()
    return len(rows)


def get_transactions(
    db: Session, user_id: uuid.UUID, upload_id: uuid.UUID, limit: int = 100, offset: int = 0
) -> list[Transaction]:
    stmt = (
        select(Transaction)
        .join(Upload, Upload.id == Transaction.upload_id)
        .where(Upload.id == upload_id, Upload.user_id == user_id)
        .order_by(Transaction.transaction_date, Transaction.id)
        .limit(limit)
        .offset(offset)
    )
    return list(db.scalars(stmt))


# --- analysis results ---

def upsert_analysis_result(
    db: Session,
    user_id: uuid.UUID,
    upload_id: uuid.UUID,
    result_type: str,
    payload: Any,
    model_version: Optional[str] = None,
) -> None:
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
