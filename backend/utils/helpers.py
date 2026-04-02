"""
Utility functions.
"""
import pandas as pd
import numpy as np
from typing import Dict, Any


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
        "num_anomalies": int(df["is_anomaly"].sum()) if "is_anomaly" in df.columns else 0,
    }

    # Category breakdown
    if "category" in df.columns:
        category_spending = (
            expenses.groupby("category")["amount"]
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
                    "category": row.get("category", row.get("predicted_category", "Uncategorized")),
                }
                for i, row in recent.iterrows()
            ]

    return summary


def safe_json_serializable(obj):
    """Convert numpy/pandas types to Python native types for JSON serialization."""
    if isinstance(obj, (np.integer,)):
        return int(obj)
    elif isinstance(obj, (np.floating,)):
        return float(obj)
    elif isinstance(obj, np.ndarray):
        return obj.tolist()
    elif isinstance(obj, pd.Timestamp):
        return obj.isoformat()
    elif isinstance(obj, pd.Period):
        return str(obj)
    elif isinstance(obj, dict):
        return {k: safe_json_serializable(v) for k, v in obj.items()}
    elif isinstance(obj, (list, tuple)):
        return [safe_json_serializable(i) for i in obj]
    return obj


def format_prediction_results(raw_res: Dict[str, Any], df: pd.DataFrame) -> Dict[str, Any]:
    """Format predictor output for the frontend."""
    if "error" in raw_res:
        return raw_res

    # Calculate historical monthly data for the chart
    historical = []
    if "date" in df.columns:
        expenses = df[df["amount"] > 0].copy()
        expenses["month"] = pd.to_datetime(expenses["date"]).dt.to_period("M").astype(str)
        monthly = expenses.groupby("month")["amount"].sum().reset_index()
        for _, row in monthly.iterrows():
            historical.append({
                "date": str(row["month"]),
                "amount": float(row["amount"]),
                "type": "actual"
            })

    # Add future predictions to plot_data
    plot_data = historical + [
        {
            "date": p["date"],
            "amount": p["predicted_spending"],
            "type": "forecast",
            "lower": p["predicted_spending"] * 0.9,
            "upper": p["predicted_spending"] * 1.1
        }
        for p in raw_res.get("future_predictions", [])
    ]

    # Model comparison as an array for the bar chart
    comparison = [
        {"model": name, "rmse": stats["rmse"], "r2": stats["r2"]}
        for name, stats in raw_res.get("model_comparison", {}).items()
    ]

    return {
        "plot_data": plot_data,
        "comparison": sorted(comparison, key=lambda x: x["rmse"]),
        "metrics": {
            "next_month_prediction": raw_res.get("total_predicted_30d", 0),
            "model_name": raw_res.get("best_model", "Predictive Engine"),
            "model_description": "Time-series forecasting ensemble",
            "top_predicted_category": "General Expenses" # Placeholder as category prediction isn't in raw_res
        }
    }


def format_anomaly_results(raw_res: Dict[str, Any], df: pd.DataFrame) -> Dict[str, Any]:
    """Format anomaly detector output for the frontend."""
    if "error" in raw_res:
        return raw_res

    # Table data - Limit to top 100 anomalies to keep the dashboard performant
    raw_flagged = raw_res.get("flagged_transactions", [])
    anomalies = []
    for i, t in enumerate(raw_flagged[:100]):
        # Calculate severity based on score
        # Decision function: lower values are more anomalous
        score = t.get("anomaly_score", 0)
        threshold = raw_res.get("score_stats", {}).get("threshold", 0)
        severity = "High" if score < threshold * 1.2 else "Medium"
        
        anomalies.append({
            "id": f"anom-{i}",
            "date": t.get("date"),
            "description": t.get("description", "Unknown transaction"),
            "amount": t.get("amount", 0),
            "score": score,
            "severity": severity
        })

    # Visualization plot data - Sub-sampling for performance (50k points will crash the UI)
    plot_data = []
    if "date" in df.columns:
        expenses = df[df["amount"] > 0].copy()
        all_labels = raw_res.get("all_labels", [])
        
        if len(all_labels) == len(expenses):
            # Include all anomalies
            anomaly_indices = [i for i, l in enumerate(all_labels) if l == -1]
            normal_indices = [i for i, l in enumerate(all_labels) if l != -1]
            
            # Sub-sample normal indices to max 500
            import random
            if len(normal_indices) > 500:
                random.seed(42)  # Deterministic sampling
                normal_indices = random.sample(normal_indices, 500)
            
            # Reconstruct the plot_data list from the selected indices
            selected_indices = sorted(anomaly_indices + normal_indices)
            
            for i in selected_indices:
                row = expenses.iloc[i]
                plot_data.append({
                    "date": row["date"].strftime("%Y-%m-%d") if pd.notna(row["date"]) else "N/A",
                    "amount": float(row["amount"]),
                    "type": "anomaly" if i in anomaly_indices else "normal"
                })

    return {
        "anomalies": anomalies,
        "plot_data": plot_data,
        "summary": {
            "total_count": raw_res.get("total_anomalies", 0),
            "rate": raw_res.get("anomaly_rate", 0)
        }
    }

def format_segmentation_results(raw_res: Dict[str, Any]) -> Dict[str, Any]:
    """Format clustering output for the frontend."""
    if "error" in raw_res:
        return raw_res

    # Map pca_x/y to x/y
    points = [
        {
            "x": p["pca_x"],
            "y": p["pca_y"],
            "cluster": p["cluster"],
            "label": p["year_month"]
        }
        for p in raw_res.get("scatter_data", [])
    ]

    # Cluster profiles
    profiles = []
    for cp in raw_res.get("cluster_profiles", []):
        profiles.append({
            **cp,
            "top_categories": ["Housing", "Utilities", "Food"], # Placeholder
            "description": f"Target group with average monthly spend of ${cp.get('avg_total_spending', 0):,.2f}."
        })

    return {
        "points": points,
        "cluster_profiles": profiles,
        "best_k": raw_res.get("best_k", 0)
    }
