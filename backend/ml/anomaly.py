"""
Anomaly detection using Isolation Forest.
"""
import pandas as pd
import numpy as np
import joblib
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import LabelEncoder
from typing import Dict, Any

from backend.core.config import MODEL_DIR, RANDOM_STATE, ANOMALY_CONTAMINATION


def detect_anomalies(df: pd.DataFrame) -> Dict[str, Any]:
    """
    Detect anomalous transactions using Isolation Forest.
    Returns anomaly labels, scores, and flagged transactions.
    """
    expenses = df[df["amount"] > 0].copy()

    if len(expenses) < 10:
        return {"error": "Not enough expense data for anomaly detection"}

    # Prepare features
    feature_cols = ["abs_amount"]
    
    if "weekday" in expenses.columns:
        feature_cols.append("weekday")
    if "month" in expenses.columns:
        feature_cols.append("month")
    if "day_of_month" in expenses.columns:
        feature_cols.append("day_of_month")
    if "is_weekend" in expenses.columns:
        feature_cols.append("is_weekend")

    # Encode category if available
    le = None
    if "category" in expenses.columns:
        le = LabelEncoder()
        expenses["category_encoded"] = le.fit_transform(expenses["category"].fillna("Unknown"))
        feature_cols.append("category_encoded")

    X = expenses[feature_cols].values

    from backend.core.config import MAX_TRAINING_SAMPLES
    
    # Isolation Forest
    iso_forest = IsolationForest(
        contamination=ANOMALY_CONTAMINATION,
        random_state=RANDOM_STATE,
        n_estimators=100,
        n_jobs=1,
    )
    
    # Fit on sample if dataset is large, but score/predict on all data
    if len(X) > MAX_TRAINING_SAMPLES:
        np.random.seed(RANDOM_STATE)
        idx = np.random.choice(len(X), MAX_TRAINING_SAMPLES, replace=False)
        X_train = X[idx]
        iso_forest.fit(X_train)
    else:
        iso_forest.fit(X)

    predictions = iso_forest.predict(X)  # 1 = normal, -1 = anomaly
    scores = iso_forest.decision_function(X)  # lower = more anomalous

    expenses["is_anomaly"] = predictions == -1
    expenses["anomaly_score"] = scores

    # Flagged transactions
    anomalies = expenses[expenses["is_anomaly"]].copy()
    anomalies = anomalies.sort_values("anomaly_score")

    flagged = []
    for _, row in anomalies.iterrows():
        flagged.append({
            "date": row["date"].strftime("%Y-%m-%d") if pd.notna(row["date"]) else "N/A",
            "amount": float(row["amount"]),
            "category": row.get("category", "N/A"),
            "description": row.get("description", "N/A"),
            "anomaly_score": float(row["anomaly_score"]),
        })

    # Save model
    model_path = MODEL_DIR / "anomaly.pkl"
    joblib.dump({"model": iso_forest, "label_encoder": le, "feature_cols": feature_cols}, model_path)

    # Score distribution stats
    normal_scores = scores[predictions == 1]
    anomaly_scores_arr = scores[predictions == -1]

    return {
        "total_transactions": len(expenses),
        "total_anomalies": int(anomalies.shape[0]),
        "anomaly_rate": float(round(len(anomalies) / len(expenses) * 100, 2)),
        "flagged_transactions": flagged,
        "score_stats": {
            "mean_normal": float(normal_scores.mean()) if len(normal_scores) > 0 else 0,
            "mean_anomaly": float(anomaly_scores_arr.mean()) if len(anomaly_scores_arr) > 0 else 0,
            "threshold": float(np.percentile(scores, ANOMALY_CONTAMINATION * 100)),
        },
        "all_scores": scores.tolist(),
        "all_labels": predictions.tolist(),
        "model_path": str(model_path),
    }
