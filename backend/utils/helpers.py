"""
Utility functions.
"""
import math
from typing import Any, Dict

import numpy as np
import pandas as pd


def format_currency(amount: float) -> str:
    """Format a number as currency string."""
    if amount >= 0:
        return f"${amount:,.2f}"
    return f"-${abs(amount):,.2f}"


def calculate_summary_stats(df: pd.DataFrame) -> Dict[str, Any]:
    """Calculate summary statistics from a transactions DataFrame."""
    expenses = df[df["amount"] > 0].copy()
    income = df[df["amount"] < 0].copy()

    summary = {
        "total_transactions": len(df),
        "total_spending": float(expenses["amount"].sum()) if len(expenses) > 0 else 0,
        "total_income": float(abs(income["amount"].sum())) if len(income) > 0 else 0,
        "avg_transaction": float(expenses["amount"].mean()) if len(expenses) > 0 else 0,
        "review_queue_size": int(df["is_anomaly"].sum()) if "is_anomaly" in df.columns else 0,
    }

    # Category breakdown, by effective category: confirmed -> your own label -> model prediction -> Uncategorized
    category_col = "effective_category" if "effective_category" in df.columns else "category"
    if category_col in df.columns:
        category_spending = (
            expenses.groupby(category_col)["amount"]
            .agg(["sum", "count"])
            .reset_index()
        )
        category_spending.columns = ["category", "amount", "count"]
        category_spending = category_spending.sort_values("amount", ascending=False)
        summary["category_spending"] = category_spending.to_dict("records")
    
    # Monthly breakdown
    if "date" in df.columns:
        expenses_with_date = expenses.dropna(subset=["date"]).copy()
        if len(expenses_with_date) > 0:
            expenses_with_date["month"] = pd.to_datetime(expenses_with_date["date"]).dt.to_period("M").astype(str)
            monthly = expenses_with_date.groupby("month")["amount"].sum().reset_index()
            monthly.columns = ["month", "amount"]
            summary["monthly_spending"] = monthly.to_dict("records")
            
            # Calculate average monthly spending
            summary["avg_monthly_spending"] = float(monthly["amount"].mean()) if len(monthly) > 0 else 0
            
            # Recent Transactions for the dashboard table
            recent = df.sort_values("date", ascending=False).head(10).copy()
            summary["recent_transactions"] = [
                {
                    "id": i,
                    "date": row["date"].strftime("%Y-%m-%d") if pd.notna(row["date"]) else "N/A",
                    "description": row.get("description", "N/A"),
                    "amount": float(row["amount"]),
                    "category": row.get(category_col, "Uncategorized"),
                }
                for i, row in recent.iterrows()
            ]

    return summary


def safe_json_serializable(obj):
    """Convert numpy/pandas types to plain Python values that PostgreSQL JSONB accepts (no NaN/Infinity)."""
    if obj is None or obj is pd.NaT:
        return None
    if isinstance(obj, (bool, np.bool_)):
        return bool(obj)
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (float, np.floating)):
        value = float(obj)
        return value if math.isfinite(value) else None
    if isinstance(obj, np.ndarray):
        return safe_json_serializable(obj.tolist())
    if isinstance(obj, pd.Timestamp):
        return obj.isoformat()
    if isinstance(obj, pd.Period):
        return str(obj)
    if isinstance(obj, dict):
        return {str(k): safe_json_serializable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [safe_json_serializable(i) for i in obj]
    return obj
