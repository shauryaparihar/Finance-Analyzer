"""
Analysis pipeline: clean the upload, categorize, forecast, rank unusual transactions, summarize.

Each module is isolated: if one fails, the others still finish and the failure is recorded.
"""
import concurrent.futures
import logging
from typing import Any, Dict

import pandas as pd

from backend.core.config import MAX_WORKERS
from backend.ml.anomaly import run_anomaly_detection
from backend.ml.forecast import run_forecast
from backend.ml.preprocessing import preprocess_full
from backend.utils.helpers import calculate_summary_stats

logger = logging.getLogger("finsight.ml")


def _run_categorization(df, categorizer):
    """Predict a category for every row with the shipped model. Nothing is trained here."""
    try:
        descriptions = df["description"] if "description" in df.columns else pd.Series([None] * len(df), index=df.index)
        return {"predictions": categorizer.predict(descriptions, df["amount"])}
    except Exception:
        logger.exception("categorization_failed")
        return {"error": "Categorization failed"}


def _run_forecast(df):
    try:
        return run_forecast(df)
    except Exception:
        logger.exception("forecast_failed")
        return {"error": "Forecast failed"}


def _run_anomaly(df):
    try:
        return run_anomaly_detection(df)
    except Exception:
        logger.exception("anomaly_failed")
        return {"error": "Unusual-transaction ranking failed"}


def _run_summary(df):
    try:
        return calculate_summary_stats(df)
    except Exception:
        logger.exception("summary_failed")
        return {"error": "Summary failed"}


def _apply_categorization(df: pd.DataFrame, cat_res: dict, categorizer, results: dict) -> None:
    """Add predicted/effective category columns. Effective: your own label, else the model's, else Uncategorized."""
    source = df["category"] if "category" in df.columns else pd.Series([None] * len(df), index=df.index)
    source = source.where(source.notna() & (source != "Uncategorized"), None)
    df["predicted_category"] = None
    df["prediction_confidence"] = None
    if "error" in cat_res:
        results["errors"].append(f"Categorization failed: {cat_res['error']}")
        df["effective_category"] = source.fillna("Uncategorized")
        return

    predictions = cat_res["predictions"]
    df["predicted_category"] = predictions["predicted_category"]
    df["prediction_confidence"] = predictions["confidence"]
    df["effective_category"] = source.fillna(df["predicted_category"]).fillna("Uncategorized")
    by_reason = predictions["reason"].value_counts().to_dict()
    total = len(df)
    auto = int((predictions["predicted_category"] != "Uncategorized").sum())
    results["modules"]["categorization"] = {
        "model_version": categorizer.version,
        "confidence_threshold": categorizer.threshold,
        "rows": total,
        "auto_categorized": auto,
        "low_confidence": int(by_reason.get("low_confidence", 0)),
        "unrecognized_text": int(by_reason.get("unrecognized_text", 0)),
        "no_description": int(by_reason.get("no_description", 0)),
        "needs_review": int((df["effective_category"] == "Uncategorized").sum()),
        "auto_categorized_rate": auto / total if total else 0.0,
        "note": "Model trained on synthetic data; low-confidence rows are left Uncategorized for your review.",
    }


def _apply_anomaly(df: pd.DataFrame, anomaly_res: dict, results: dict) -> None:
    """Store the review-queue columns on the dataframe and the summary as a module result."""
    df["anomaly_score"] = None
    df["anomaly_rank"] = None
    df["anomaly_reason"] = None
    if "error" in anomaly_res:
        results["errors"].append(f"Unusual-transaction ranking failed: {anomaly_res['error']}")
        return
    columns = anomaly_res.pop("row_columns")
    if columns is not None:
        for name in ("anomaly_score", "anomaly_rank", "anomaly_reason"):
            df[name] = columns[name].reindex(df.index).astype(object)
    results["modules"]["anomaly"] = anomaly_res


def run_full_pipeline(df: pd.DataFrame, categorizer) -> Dict[str, Any]:
    """Run the complete analysis on validated upload data."""
    results: Dict[str, Any] = {"status": "completed", "modules": {}, "errors": []}

    try:
        df = preprocess_full(df)
        results["modules"]["preprocessing"] = {
            "status": "success",
            "rows_after_cleaning": len(df),
            "columns": list(df.columns),
        }
    except Exception:
        logger.exception("preprocessing_failed")
        results["errors"].append("Preprocessing failed")
        results["status"] = "failed"
        return results

    # Categorization and forecasting do not depend on each other.
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        categorization = executor.submit(_run_categorization, df, categorizer)
        forecast = executor.submit(_run_forecast, df)
        cat_res, forecast_res = categorization.result(), forecast.result()

    _apply_categorization(df, cat_res, categorizer, results)

    if "error" in forecast_res:
        results["errors"].append(f"Forecast failed: {forecast_res['error']}")
    else:
        results["modules"]["forecast"] = forecast_res

    # Ranking unusual transactions needs each row's effective category, so it runs after categorization.
    _apply_anomaly(df, _run_anomaly(df), results)
    df["is_anomaly"] = df["anomaly_rank"].notna()

    summary = _run_summary(df)
    if "error" in summary:
        results["errors"].append(f"Summary failed: {summary['error']}")
    else:
        results["modules"]["summary"] = summary

    results["processed_df"] = df
    logger.info("pipeline_finished rows=%s errors=%s", len(df), len(results["errors"]))
    return results
