"""
ML Pipeline Orchestrator — runs the full analysis pipeline.
"""
import concurrent.futures
import logging
import traceback
from typing import Any, Dict

import pandas as pd

from backend.ml.anomaly import detect_anomalies
from backend.ml.forecast import run_forecast
from backend.ml.preprocessing import preprocess_full
from backend.ml.segmentation import segment_spending
from backend.utils.helpers import (
    calculate_summary_stats,
    format_anomaly_results,
    format_segmentation_results,
)

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
        return detect_anomalies(df)
    except Exception as e:
        traceback.print_exc()
        return {"error": str(e)}

def _run_segmentation(df):
    try:
        return segment_spending(df)
    except Exception as e:
        traceback.print_exc()
        return {"error": str(e)}

def _run_summary(df):
    try:
        return calculate_summary_stats(df)
    except Exception as e:
        traceback.print_exc()
        return {"error": str(e)}

def run_full_pipeline(df: pd.DataFrame, categorizer) -> Dict[str, Any]:
    """
    Run the complete ML pipeline on uploaded transaction data concurrently.
    """
    from backend.core.config import MAX_WORKERS
    
    results = {
        "status": "completed",
        "modules": {},
        "errors": [],
    }

    print("\n🔧 Step 1: Preprocessing data...")
    try:
        df = preprocess_full(df)
        results["modules"]["preprocessing"] = {
            "status": "success",
            "rows_after_cleaning": len(df),
            "columns": list(df.columns),
        }
    except Exception as e:
        results["errors"].append(f"Preprocessing failed: {str(e)}")
        results["status"] = "failed"
        traceback.print_exc()
        return results

    print(f"\n🚀 Step 2: Running ML modules concurrently ({MAX_WORKERS} workers)...")
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        f_cat = executor.submit(_run_categorization, df, categorizer)
        f_pred = executor.submit(_run_forecast, df)
        f_anom = executor.submit(_run_anomaly, df)
        f_seg = executor.submit(_run_segmentation, df)
        
        # Wait for and collect results
        cat_res = f_cat.result()
        pred_res = f_pred.result()
        anom_res = f_anom.result()
        seg_res = f_seg.result()

    # Process and assign categorization
    source = df["category"] if "category" in df.columns else pd.Series([None] * len(df), index=df.index)
    source = source.where(source.notna() & (source != "Uncategorized"), None)
    df["predicted_category"] = None
    df["prediction_confidence"] = None
    if "error" in cat_res:
        results["errors"].append(f"Categorization failed: {cat_res['error']}")
        df["effective_category"] = source.fillna("Uncategorized")
    else:
        predictions = cat_res["predictions"]
        df["predicted_category"] = predictions["predicted_category"]
        df["prediction_confidence"] = predictions["confidence"]
        # Effective category: your own label first, otherwise the model's, otherwise Uncategorized.
        df["effective_category"] = source.fillna(df["predicted_category"]).fillna("Uncategorized")
        by_reason = predictions["reason"].value_counts().to_dict()
        total = len(df)
        results["modules"]["categorization"] = {
            "model_version": categorizer.version,
            "confidence_threshold": categorizer.threshold,
            "rows": total,
            "auto_categorized": int((predictions["predicted_category"] != "Uncategorized").sum()),
            "low_confidence": int(by_reason.get("low_confidence", 0)),
            "no_description": int(by_reason.get("no_description", 0)),
            "needs_review": int((df["effective_category"] == "Uncategorized").sum()),
            "auto_categorized_rate": float((predictions["predicted_category"] != "Uncategorized").mean()) if total else 0.0,
            "note": "Model trained on synthetic data; low-confidence rows are left Uncategorized for your review.",
        }

    # Process and assign forecast
    if "error" in pred_res:
        results["errors"].append(f"Forecast failed: {pred_res['error']}")
    else:
        results["modules"]["forecast"] = pred_res

    # Process and assign anomaly
    if "error" in anom_res:
        results["errors"].append(f"Anomaly detection failed: {anom_res['error']}")
    else:
        results["modules"]["anomaly"] = format_anomaly_results(anom_res, df)
        expenses = df[df["amount"] > 0].copy()
        if len(anom_res.get("all_labels", [])) == len(expenses):
            df["is_anomaly"] = False
            df["anomaly_score"] = 0.0
            
            # Using bool() to explicitly ensure boolean type to prevent pandas coercion issues
            anomaly_flags = [bool(label == -1) for label in anom_res["all_labels"]]
            df.loc[expenses.index, "is_anomaly"] = anomaly_flags
            df.loc[expenses.index, "anomaly_score"] = anom_res["all_scores"]

    # Process and assign segmentation
    if "error" in seg_res:
        results["errors"].append(f"Segmentation failed: {seg_res['error']}")
    else:
        results["modules"]["segmentation"] = format_segmentation_results(seg_res)

    # FINALLY run summary stats on the fully processed dataframe
    print(f"\n📊 Step 3: Calculating final summary statistics on {len(df)} rows...")
    print(f"    Available columns for summary: {list(df.columns)}")
    if "is_anomaly" in df.columns:
        print(f"    Anomalies found in DF: {df['is_anomaly'].sum()}")
    
    sum_res = _run_summary(df)
    
    if "error" in sum_res:
        print(f"    ❌ Summary stats failed: {sum_res['error']}")
        results["errors"].append(f"Summary stats failed: {sum_res['error']}")
    else:
        print(f"    ✅ Summary stats calculated. Keys: {list(sum_res.keys())}")
        if "avg_monthly_spending" in sum_res:
            print(f"    ⭐ Avg Monthly Spend: {sum_res['avg_monthly_spending']}")
        results["modules"]["summary"] = sum_res

    results["processed_df"] = df

    print(f"\n{'='*50}")
    print(f"Pipeline completed: {len(results['errors'])} errors")
    print(f"{'='*50}\n")

    return results
