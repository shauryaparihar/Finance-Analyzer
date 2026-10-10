"""
ORM models. Every user-owned table can be traced back to a user through user_id.
"""
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.core.database import Base

UPLOAD_STATUSES = ("queued", "processing", "completed", "partial", "failed")
MODULES = ("categorization", "forecast", "anomaly", "summary")
RUN_STATUSES = ("pending", "running", "completed", "failed", "skipped")
REVIEW_STATUSES = ("unreviewed", "confirmed", "dismissed")
ROLES = ("user", "admin", "demo")  # demo = read-only guest account


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


class User(Base):
    __tablename__ = "users"
    __table_args__ = (CheckConstraint(_in("role", ROLES), name="ck_users_role"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    role: Mapped[str] = mapped_column(String(10), nullable=False, default="user", server_default="user")
    # Google's stable id for this person (the "sub" claim), set when they sign in with Google.
    google_sub: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, unique=True)

    uploads: Mapped[list["Upload"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    budgets: Mapped[list["Budget"]] = relationship(back_populates="user", cascade="all, delete-orphan")


class Upload(Base):
    __tablename__ = "uploads"
    __table_args__ = (
        CheckConstraint(_in("status", UPLOAD_STATUSES), name="ck_uploads_status"),
        # Not unique: a failed upload may be retried with the same file. Used to find a finished result to reuse.
        Index("ix_uploads_user_id_content_sha256", "user_id", "content_sha256"),
        # At most one queued/processing upload per user, enforced by the database itself.
        # Workers look for the oldest queued job and for processing jobs with a stale heartbeat.
        Index("ix_uploads_queued", "created_at", postgresql_where=text("status = 'queued'")),
        Index("ix_uploads_processing_heartbeat", "heartbeat_at", postgresql_where=text("status = 'processing'")),
        Index(
            "uq_uploads_one_active_per_user",
            "user_id",
            unique=True,
            postgresql_where=text("status IN ('queued', 'processing')"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    row_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # The sign convention applied at upload; part of the duplicate-result key, because it changes the results.
    amount_convention: Mapped[Optional[str]] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="queued", server_default="queued")
    error_summary: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    # Durable job queue: a `queued` upload is a job. A worker claims it (status -> processing, claimed_by = that
    # worker) and keeps heartbeat_at fresh while it runs; a stale heartbeat means the worker died.
    claimed_by: Mapped[Optional[str]] = mapped_column(String(100))
    heartbeat_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    request_id: Mapped[Optional[str]] = mapped_column(String(64))  # the request that queued it, for log correlation

    user: Mapped[User] = relationship(back_populates="uploads")
    transactions: Mapped[list["Transaction"]] = relationship(back_populates="upload", passive_deletes=True)
    analysis_runs: Mapped[list["AnalysisRun"]] = relationship(back_populates="upload", passive_deletes=True)
    analysis_results: Mapped[list["AnalysisResult"]] = relationship(back_populates="upload", passive_deletes=True)


class Transaction(Base):
    __tablename__ = "transactions"
    __table_args__ = (
        CheckConstraint(_in("anomaly_review_status", REVIEW_STATUSES), name="ck_transactions_review_status"),
        Index("ix_transactions_upload_id_transaction_date", "upload_id", "transaction_date"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    upload_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("uploads.id", ondelete="CASCADE"), nullable=False, index=True)
    transaction_date: Mapped[Optional[date]] = mapped_column(Date)
    # Fixed precision: floats cannot represent most cents exactly, which adds up to wrong totals.
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String(500))  # never log this value
    source_category: Mapped[Optional[str]] = mapped_column(String(100))
    predicted_category: Mapped[Optional[str]] = mapped_column(String(100))
    prediction_confidence: Mapped[Optional[float]] = mapped_column(Float)
    confirmed_category: Mapped[Optional[str]] = mapped_column(String(100))
    anomaly_score: Mapped[Optional[float]] = mapped_column(Float)
    anomaly_rank: Mapped[Optional[int]] = mapped_column(Integer)
    anomaly_reason: Mapped[Optional[str]] = mapped_column(String(300))
    anomaly_review_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="unreviewed", server_default="unreviewed"
    )

    upload: Mapped[Upload] = relationship(back_populates="transactions")


class AnalysisRun(Base):
    __tablename__ = "analysis_runs"
    __table_args__ = (
        UniqueConstraint("upload_id", "module", name="uq_analysis_runs_upload_module"),
        CheckConstraint(_in("module", MODULES), name="ck_analysis_runs_module"),
        CheckConstraint(_in("status", RUN_STATUSES), name="ck_analysis_runs_status"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    upload_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("uploads.id", ondelete="CASCADE"), nullable=False, index=True)
    module: Mapped[str] = mapped_column(String(30), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending", server_default="pending")
    model_version: Mapped[Optional[str]] = mapped_column(String(100))
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer)
    error_code: Mapped[Optional[str]] = mapped_column(String(100))
    error_message: Mapped[Optional[str]] = mapped_column(Text)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    upload: Mapped[Upload] = relationship(back_populates="analysis_runs")


class AnalysisResult(Base):
    __tablename__ = "analysis_results"
    __table_args__ = (UniqueConstraint("upload_id", "result_type", name="uq_analysis_results_upload_type"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    upload_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("uploads.id", ondelete="CASCADE"), nullable=False, index=True)
    result_type: Mapped[str] = mapped_column(String(50), nullable=False)
    payload: Mapped[Any] = mapped_column(JSONB, nullable=False)
    model_version: Mapped[Optional[str]] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    upload: Mapped[Upload] = relationship(back_populates="analysis_results")


class Budget(Base):
    __tablename__ = "budgets"
    __table_args__ = (
        UniqueConstraint("user_id", "category", name="uq_budgets_user_category"),
        CheckConstraint("monthly_limit > 0", name="ck_budgets_limit_positive"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    category: Mapped[str] = mapped_column(String(100), nullable=False)
    monthly_limit: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    user: Mapped[User] = relationship(back_populates="budgets")


class UploadInput(Base):
    """The cleaned input of a queued/running job (gzipped CSV). Deleted when the job finishes, so raw statement
    data is not kept longer than it is needed to run the analysis."""

    __tablename__ = "upload_inputs"

    upload_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("uploads.id", ondelete="CASCADE"), primary_key=True)
    data: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class RefreshToken(Base):
    """A long-lived login credential, stored only as a hash. Tokens rotate: using one revokes it and issues the next
    in the same family. Presenting a token that was already rotated (outside a short grace window) means it may have
    been stolen, so the whole family is revoked."""

    __tablename__ = "refresh_tokens"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    family_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    family_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    revoke_reason: Mapped[Optional[str]] = mapped_column(String(20))  # rotated | logout | reuse
    replaced_by_id: Mapped[Optional[uuid.UUID]] = mapped_column(Uuid)
