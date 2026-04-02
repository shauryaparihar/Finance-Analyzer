"""
Pydantic schemas for API request/response validation.
"""
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
from datetime import datetime


class UploadResponse(BaseModel):
    upload_id: int
    filename: str
    num_rows: int
    status: str
    message: str


class TransactionOut(BaseModel):
    id: int
    date: Optional[str] = None
    amount: float
    category: Optional[str] = None
    description: Optional[str] = None
    predicted_category: Optional[str] = None
    is_anomaly: bool = False
    anomaly_score: Optional[float] = None
    cluster_label: Optional[int] = None


class UploadInfo(BaseModel):
    id: int
    filename: str
    upload_date: str
    num_rows: int
    status: str


class PipelineResultOut(BaseModel):
    result_type: str
    data: Dict[str, Any]


class SummaryOut(BaseModel):
    total_transactions: int
    total_spending: float
    total_income: float
    avg_transaction: float
    avg_monthly_spending: Optional[float] = 0.0
    num_anomalies: Optional[int] = 0
    top_category: Optional[str] = None
    category_spending: Optional[List[Dict[str, Any]]] = None
    category_breakdown: Optional[List[Dict[str, Any]]] = None  # Legacy support
    monthly_spending: Optional[List[Dict[str, Any]]] = None
    
    # Legacy fields
    median_transaction: Optional[float] = 0.0
    max_transaction: Optional[float] = 0.0
    min_transaction: Optional[float] = 0.0
    std_transaction: Optional[float] = 0.0
