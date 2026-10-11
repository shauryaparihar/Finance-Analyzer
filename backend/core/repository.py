"""
Data-access functions. Every function that touches user-owned data takes the user's id and
applies it inside the SQL query, so another user's rows can never be returned or changed.
"""
import uuid
from datetime import datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Optional

import pandas as pd
from sqlalchemy import and_, delete, func, insert, or_, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from backend.core.models import MODULES, AnalysisResult, AnalysisRun, Budget, Transaction, Upload, UploadInput, User
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


class ClaimLost(RuntimeError):
    """This worker no longer owns the job (its heartbeat lapsed and the job was handed to another attempt)."""
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
    db: Session,
    user_id: uuid.UUID,
    upload_id: uuid.UUID,
    status: str,
    error_summary: Optional[str] = None,
    worker_id: Optional[str] = None,
) -> bool:
    """Move an upload to a new status. With worker_id, only the worker that still owns the claim may do it."""
    stmt = select(Upload).where(Upload.id == upload_id, Upload.user_id == user_id)
    if worker_id is not None:
        stmt = stmt.with_for_update()  # lock the row so a concurrent reaper cannot change it under us
    upload = db.scalar(stmt)
    if upload is None:
        return False
    if worker_id is not None and (upload.claimed_by != worker_id or upload.status != "processing"):
        raise ClaimLost(f"{upload_id} is no longer claimed by {worker_id}")
    if status not in ALLOWED_TRANSITIONS.get(upload.status, set()):
        raise InvalidStatusTransition(f"{upload.status} -> {status}")
    upload.status = status
    upload.error_summary = error_summary
    if status in TERMINAL_UPLOAD_STATUSES:
        upload.completed_at = datetime.now(timezone.utc)
        db.execute(delete(UploadInput).where(UploadInput.upload_id == upload_id))  # the input is no longer needed
    db.commit()
    return True


def delete_upload(db: Session, user_id: uuid.UUID, upload_id: uuid.UUID) -> bool:
    """Delete an upload owned by user_id. Dependent rows are removed by the database (ON DELETE CASCADE)."""
    result = db.execute(delete(Upload).where(Upload.id == upload_id, Upload.user_id == user_id))
    db.commit()
    return result.rowcount > 0


# --- transactions ---

def store_transactions(
    db: Session, user_id: uuid.UUID, upload_id: uuid.UUID, df: pd.DataFrame, commit: bool = True
) -> int:
    """Bulk-insert processed transactions into an upload owned by user_id. commit=False lets a caller group this
    with other writes in one transaction."""
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
    if commit:
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
    commit: bool = True,
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
    if commit:
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


def enqueue_upload(
    db: Session,
    user_id: uuid.UUID,
    filename: str,
    content_sha256: str,
    row_count: int,
    amount_convention: str,
    input_data: bytes,
    request_id: Optional[str] = None,
) -> Upload:
    """Queue a job: the upload, its pending module runs and its input are saved together or not at all."""
    upload = Upload(
        user_id=user_id,
        original_filename=filename,
        content_sha256=content_sha256,
        row_count=row_count,
        amount_convention=amount_convention,
        request_id=request_id,
    )
    db.add(upload)
    db.flush()  # raises IntegrityError here if the user already has an active job (partial unique index)
    db.add(UploadInput(upload_id=upload.id, data=input_data))
    db.execute(insert(AnalysisRun), [{"upload_id": upload.id, "module": m, "status": "pending"} for m in MODULES])
    db.commit()
    db.refresh(upload)
    return upload


def claim_next_job(db: Session, worker_id: str) -> Optional[Upload]:
    """Atomically take the oldest queued job. SKIP LOCKED means workers (in any instance) never wait for or
    double-take the same row."""
    stmt = (
        select(Upload).where(Upload.status == "queued").order_by(Upload.created_at).limit(1).with_for_update(skip_locked=True)
    )
    upload = db.scalar(stmt)
    if upload is None:
        db.rollback()
        return None
    upload.status = "processing"
    upload.claimed_by = worker_id
    upload.heartbeat_at = func.now()
    upload.attempts = upload.attempts + 1
    db.commit()
    db.refresh(upload)
    return upload


def require_claim(db: Session, user_id: uuid.UUID, upload_id: uuid.UUID, worker_id: str) -> None:
    """Fencing: raise ClaimLost unless this worker still owns the processing job."""
    owner = db.execute(
        select(Upload.claimed_by, Upload.status).where(Upload.id == upload_id, Upload.user_id == user_id)
    ).one_or_none()
    if owner is None:
        raise LookupError("Upload not found")
    if owner.claimed_by != worker_id or owner.status != "processing":
        raise ClaimLost(f"{upload_id} is no longer claimed by {worker_id}")


def lock_claim(db: Session, user_id: uuid.UUID, upload_id: uuid.UUID, worker_id: str) -> None:
    """Lock the job row and verify this worker still owns it. The lock is held until the caller commits or rolls
    back, so a reaper (which skips locked rows) cannot hand the job to another worker in the middle of the writes."""
    owner = db.execute(
        select(Upload.claimed_by, Upload.status)
        .where(Upload.id == upload_id, Upload.user_id == user_id)
        .with_for_update()
    ).one_or_none()
    if owner is None:
        raise LookupError("Upload not found")
    if owner.claimed_by != worker_id or owner.status != "processing":
        raise ClaimLost(f"{upload_id} is no longer claimed by {worker_id}")


def get_job_input(db: Session, upload_id: uuid.UUID) -> Optional[bytes]:
    return db.scalar(select(UploadInput.data).where(UploadInput.upload_id == upload_id))


def beat(db: Session, upload_id: uuid.UUID, worker_id: str) -> bool:
    """Prove the job is still alive. Returns False if this worker no longer owns it. If the job row is locked (the
    worker is saving its results), skip this beat: the lock itself shows the job is alive."""
    db.execute(text("SET LOCAL lock_timeout = '1s'"))
    try:
        result = db.execute(
            update(Upload)
            .where(Upload.id == upload_id, Upload.claimed_by == worker_id, Upload.status == "processing")
            .values(heartbeat_at=func.now())
        )
    except OperationalError:
        db.rollback()
        return True
    db.commit()
    return result.rowcount > 0


def reset_for_retry(db: Session, user_id: uuid.UUID, upload_id: uuid.UUID) -> None:
    """Clear what a previous, interrupted attempt may have written so the retry starts clean (no duplicates)."""
    if get_upload(db, user_id, upload_id) is None:
        raise LookupError("Upload not found")
    db.execute(delete(Transaction).where(Transaction.upload_id == upload_id))
    db.execute(delete(AnalysisResult).where(AnalysisResult.upload_id == upload_id))
    db.execute(
        update(AnalysisRun)
        .where(AnalysisRun.upload_id == upload_id)
        .values(
            status="pending", duration_ms=None, model_version=None, error_code=None, error_message=None,
            started_at=None, finished_at=None,
        )
    )
    db.commit()


def reap_orphaned_jobs(db: Session, stale_after_seconds: float, max_attempts: int) -> dict[str, int]:
    """Recover jobs whose worker died (no heartbeat for stale_after_seconds): re-queue them, or fail them once they
    have been attempted max_attempts times. Jobs with a fresh heartbeat are never touched, whichever instance runs
    them. Time is measured by the database, so instances need no synchronised clocks."""
    cutoff = func.now() - timedelta(seconds=stale_after_seconds)
    orphans = list(
        db.scalars(
            select(Upload)
            .where(Upload.status == "processing", Upload.heartbeat_at < cutoff)
            .with_for_update(skip_locked=True)
        )
    )
    requeued = failed = 0
    for upload in orphans:
        if upload.attempts < max_attempts:
            upload.status, upload.claimed_by, upload.heartbeat_at = "queued", None, None
            requeued += 1
        else:
            reason = "Analysis was interrupted repeatedly and was given up."
            upload.status, upload.error_summary, upload.completed_at = "failed", reason, datetime.now(timezone.utc)
            db.execute(delete(UploadInput).where(UploadInput.upload_id == upload.id))
            db.execute(
                update(AnalysisRun)
                .where(AnalysisRun.upload_id == upload.id, AnalysisRun.status.in_(("pending", "running")))
                .values(status="failed", error_code="INTERRUPTED", error_message=reason, finished_at=datetime.now(timezone.utc))
            )
            failed += 1
    db.commit()
    return {"requeued": requeued, "failed": failed}


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


# --- accounts: roles, demo and admin summaries (aggregates only, never financial rows) ---

DEMO_EMAIL = "demo@example.com"
UNUSABLE_PASSWORD_HASH = "!"  # not an Argon2 hash, so no password can ever match it


def get_or_create_demo_user(db: Session) -> User:
    user = get_user_by_email(db, DEMO_EMAIL)
    if user is not None:
        return user
    user = User(email=DEMO_EMAIL, password_hash=UNUSABLE_PASSWORD_HASH, role="demo")
    db.add(user)
    try:
        db.commit()
    except IntegrityError:  # two guests arriving at the same moment
        db.rollback()
        return get_user_by_email(db, DEMO_EMAIL)  # type: ignore[return-value]
    db.refresh(user)
    return user


def admin_overview(db: Session) -> dict:
    users_by_role = {role: n for role, n in db.execute(select(User.role, func.count()).group_by(User.role)).all()}
    uploads_by_status = {st: n for st, n in db.execute(select(Upload.status, func.count()).group_by(Upload.status)).all()}
    week_ago = func.now() - text("interval '7 days'")
    return {
        "users_total": sum(users_by_role.values()),
        "users_active": int(db.scalar(select(func.count()).select_from(User).where(User.is_active.is_(True))) or 0),
        "users_by_role": users_by_role,
        "uploads_total": sum(uploads_by_status.values()),
        "uploads_by_status": uploads_by_status,
        "uploads_last_7_days": int(db.scalar(select(func.count()).select_from(Upload).where(Upload.created_at >= week_ago)) or 0),
    }


def admin_list_users(db: Session, limit: int = 200) -> list[dict]:
    counts = select(Upload.user_id, func.count().label("n")).group_by(Upload.user_id).subquery()
    rows = db.execute(
        select(User, func.coalesce(counts.c.n, 0))
        .outerjoin(counts, counts.c.user_id == User.id)
        .order_by(User.created_at.desc())
        .limit(limit)
    ).all()
    return [
        {"id": u.id, "email": u.email, "role": u.role, "is_active": u.is_active, "created_at": u.created_at, "upload_count": int(n)}
        for u, n in rows
    ]


def set_user_active(db: Session, user_id: uuid.UUID, active: bool) -> Optional[User]:
    user = db.get(User, user_id)
    if user is None:
        return None
    user.is_active = active
    db.commit()
    db.refresh(user)
    return user


def resolve_google_user(db: Session, google_sub: str, email: str) -> tuple[User, bool]:
    """The account for a verified Google identity. Returns (user, linked_existing_account).

    * known Google id            -> that account
    * unknown id, email in use   -> link Google to that account. The account's password is switched off and its
                                    sessions are ended by the caller: otherwise someone who registered the victim's
                                    email first (the app never verified it) could keep using their own password.
    * otherwise                  -> a new ordinary account with no password
    """
    user = db.scalar(select(User).where(User.google_sub == google_sub))
    if user is not None:
        return user, False
    existing = get_user_by_email(db, email)
    if existing is not None:
        if existing.role == "demo":
            raise ValueError("the demo account cannot be linked")
        existing.google_sub = google_sub
        existing.password_hash = UNUSABLE_PASSWORD_HASH
        existing.email_verified_at = existing.email_verified_at or func.now()  # Google vouches for the address
        db.commit()
        db.refresh(existing)
        return existing, True
    user = User(email=email.strip().lower(), password_hash=UNUSABLE_PASSWORD_HASH, google_sub=google_sub, email_verified_at=func.now())
    db.add(user)
    db.commit()
    db.refresh(user)
    return user, False


def set_password_and_verify(db: Session, user_id: uuid.UUID, password_hash: str) -> None:
    """After a successful reset by emailed link: new password, and the address is now proven to be theirs."""
    user = db.get(User, user_id)
    user.password_hash = password_hash
    user.email_verified_at = user.email_verified_at or func.now()
    db.commit()


def mark_email_verified(db: Session, user_id: uuid.UUID) -> None:
    user = db.get(User, user_id)
    if user.email_verified_at is None:
        user.email_verified_at = func.now()
        db.commit()
