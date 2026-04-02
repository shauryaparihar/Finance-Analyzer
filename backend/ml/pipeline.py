"""
ML Pipeline Orchestrator — runs the full analysis pipeline.
"""
import pandas as pd
import traceback
from typing import Dict, Any

from backend.ml.preprocessing import preprocess_full, prepare_for_classification, prepare_for_regression
from backend.ml.categorizer import train_categorizer, predict_categories
from backend.ml.predictor import train_predictor
from backend.ml.anomaly import detect_anomalies
from backend.ml.segmentation import segment_spending
from backend.utils.helpers import (
    calculate_summary_stats, 
    safe_json_serializable,
    format_prediction_results,
    format_anomaly_results,
    format_segmentation_results
)


import concurrent.futures

def _run_categorization(df):
    try:
        feature_matrix, labels, vectorizer = prepare_for_classification(df)
        return train_categorizer(feature_matrix, labels, vectorizer)
    except Exception as e:
        traceback.print_exc()
        return {"error": str(e)}

def _run_prediction(df):
    try:
        daily = prepare_for_regression(df, freq="D")
        return train_predictor(daily)
    except Exception as e:
        traceback.print_exc()
        return {"error": str(e)}

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

def run_full_pipeline(df: pd.DataFrame) -> Dict[str, Any]:
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
        f_cat = executor.submit(_run_categorization, df)
        f_pred = executor.submit(_run_prediction, df)
        f_anom = executor.submit(_run_anomaly, df)
        f_seg = executor.submit(_run_segmentation, df)
        
        # Wait for and collect results
        cat_res = f_cat.result()
        pred_res = f_pred.result()
        anom_res = f_anom.result()
        seg_res = f_seg.result()

    # Process and assign categorization
    if "error" in cat_res:
        results["errors"].append(f"Categorization failed: {cat_res['error']}")
    else:
        results["modules"]["categorization"] = cat_res
        try:
            from backend.ml.categorizer import load_categorizer
            model, vec = load_categorizer()
            if model and vec:
                df["predicted_category"] = predict_categories(df, vec, model)
        except Exception:
            pass

    # Process and assign prediction
    if "error" in pred_res:
        results["errors"].append(f"Prediction failed: {pred_res['error']}")
    else:
        results["modules"]["prediction"] = format_prediction_results(pred_res, df)

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
            anomaly_flags = [bool(l == -1) for l in anom_res["all_labels"]]
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
