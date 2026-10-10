"""
Pydantic schemas for API request/response validation.
"""
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal, Optional

from pydantic import BaseModel, EmailStr, Field


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class UserOut(BaseModel):
    id: uuid.UUID
    email: str
    created_at: datetime


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int  # seconds


class UploadAccepted(BaseModel):
    upload_id: uuid.UUID
    filename: str
    status: str
    reused: bool = False  # true: you already had this exact file analysed, so that analysis is returned
    rows_received: int
    rows_dropped: int
    amount_convention: str
    message: str


class UploadOut(BaseModel):
    id: uuid.UUID
    filename: str
    row_count: int
    status: str
    error_summary: Optional[str] = None
    created_at: datetime
    completed_at: Optional[datetime] = None


class ModuleStatusOut(BaseModel):
    module: str
    status: str  # pending | running | completed | failed | skipped
    duration_ms: Optional[int] = None
    model_version: Optional[str] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None


class UploadStatusOut(BaseModel):
    upload_id: uuid.UUID
    status: str  # queued | processing | completed | partial | failed
    error_summary: Optional[str] = None
    modules: list[ModuleStatusOut] = []


class TransactionOut(BaseModel):
    id: int
    date: Optional[str] = None
    amount: float
    category: str
    description: Optional[str] = None
    source_category: Optional[str] = None  # the category written in the uploaded file, if any
    predicted_category: Optional[str] = None
    prediction_confidence: Optional[float] = None
    confirmed_category: Optional[str] = None
    review_required: bool = False
    anomaly_score: Optional[float] = None
    anomaly_rank: Optional[int] = None
    anomaly_reason: Optional[str] = None
    anomaly_review_status: str = "unreviewed"


class TransactionsPage(BaseModel):
    upload_id: uuid.UUID
    count: int
    limit: int
    offset: int
    transactions: list[TransactionOut]


class ResultOut(BaseModel):
    result_type: str
    data: Any


class CategoryUpdate(BaseModel):
    category: str = Field(min_length=1, max_length=100)


class BudgetIn(BaseModel):
    monthly_limit: Decimal = Field(gt=0, le=100_000_000, decimal_places=2)


class BudgetOut(BaseModel):
    category: str
    monthly_limit: float
    created_at: datetime
    updated_at: datetime


class AnomalyReviewUpdate(BaseModel):
    status: Literal["confirmed", "dismissed", "unreviewed"]


class UnusualTransaction(BaseModel):
    transaction_id: int
    rank: int
    date: Optional[str] = None
    description: Optional[str] = None
    amount: float
    category: str
    score: Optional[float] = None
    reason: Optional[str] = None
    review_status: str


class AnomaliesOut(BaseModel):
    status: str  # completed | skipped | not_available
    reason: Optional[str] = None
    method: Optional[str] = None
    review_capacity: Optional[int] = None
    expenses_scanned: Optional[int] = None
    reviewed: int = 0
    confirmed: int = 0
    dismissed: int = 0
    decisions_outside_queue: int = 0  # earlier decisions on transactions that have since left the queue
    items: list[UnusualTransaction] = []
    disclaimer: str
