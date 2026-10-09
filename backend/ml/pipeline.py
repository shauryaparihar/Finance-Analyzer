"""
Analysis pipeline: clean the upload, categorize, forecast, rank unusual transactions, summarize.

Each module is isolated: if one fails, the others still finish and the failure is recorded.
"""
import concurrent.futures
import contextvars
import logging
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional

import pandas as pd

from backend.core.config import MAX_WORKERS
from backend.ml.anomaly import run_anomaly_detection
from backend.ml.forecast import run_forecast
from backend.ml.preprocessing import preprocess_full
from backend.utils.helpers import calculate_summary_stats

logger = logging.getLogger("finsight.ml")


@dataclass
class ModuleOutcome:
    """How one analysis module ended. `skipped` means "not enough data", which is not a failure."""

    status: str  # completed | failed | skipped
    model_version: Optional[str] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None  # always safe to show to the user


class NullObserver:
    """Receives module progress events; the default ignores them."""

    def on_start(self, module: str) -> None: ...

    def on_finish(self, module: str, outcome: ModuleOutcome, duration_ms: int) -> None: ...


def _observed(module: str, fn: Callable, args: tuple, observer, classify: Callable[[dict], ModuleOutcome]):
    """Run one module, timing it and reporting its start and outcome."""
    observer.on_start(module)
    started = time.perf_counter()
    result = fn(*args)
    observer.on_finish(module, classify(result), int((time.perf_counter() - started) * 1000))
    return result


def _classify_categorization(categorizer):
    def classify(result: dict) -> ModuleOutcome:
        if "error" in result:
            return ModuleOutcome("failed", error_code="CATEGORIZATION_FAILED", error_message="Categorization failed.")
        return ModuleOutcome("completed", model_version=categorizer.version)

    return classify


def _classify_with_status(failed_code: str, failed_message: str, skipped_code: str):
    """For modules whose result may carry status 'skipped' (not enough data) or an 'error' key."""

    def classify(result: dict) -> ModuleOutcome:
        if "error" in result:
            return ModuleOutcome("failed", error_code=failed_code, error_message=failed_message)
        if result.get("status") == "skipped":
            return ModuleOutcome("skipped", error_code=skipped_code, error_message=result.get("reason"))
        return ModuleOutcome("completed", model_version=result.get("method"))

    return classify


_classify_forecast = _classify_with_status("FORECAST_FAILED", "Forecast failed.", "INSUFFICIENT_HISTORY")
_classify_anomaly = _classify_with_status("ANOMALY_FAILED", "Unusual-transaction ranking failed.", "INSUFFICIENT_DATA")
_classify_summary = _classify_with_status("SUMMARY_FAILED", "Summary failed.", "NOT_AVAILABLE")


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


def run_full_pipeline(df: pd.DataFrame, categorizer, observer=None) -> Dict[str, Any]:
    """Run the complete analysis on validated upload data, reporting each module's progress to `observer`."""
    observer = observer or NullObserver()
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
        # Worker threads do not inherit context variables, so each task runs in a copy of this thread's context:
        # that keeps the request id on the log lines they write.
        categorization = executor.submit(
            contextvars.copy_context().run,
            _observed, "categorization", _run_categorization, (df, categorizer), observer, _classify_categorization(categorizer),
        )
        forecast = executor.submit(
            contextvars.copy_context().run, _observed, "forecast", _run_forecast, (df,), observer, _classify_forecast
        )
        cat_res, forecast_res = categorization.result(), forecast.result()

    _apply_categorization(df, cat_res, categorizer, results)

    if "error" in forecast_res:
        results["errors"].append(f"Forecast failed: {forecast_res['error']}")
    else:
        results["modules"]["forecast"] = forecast_res

    # Ranking unusual transactions needs each row's effective category, so it runs after categorization.
    _apply_anomaly(df, _observed("anomaly", _run_anomaly, (df,), observer, _classify_anomaly), results)
    df["is_anomaly"] = df["anomaly_rank"].notna()

    summary = _observed("summary", _run_summary, (df,), observer, _classify_summary)
    if "error" in summary:
        results["errors"].append(f"Summary failed: {summary['error']}")
    else:
        results["modules"]["summary"] = summary

    results["processed_df"] = df
    logger.info("pipeline_finished rows=%s errors=%s", len(df), len(results["errors"]))
    return results
