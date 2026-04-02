"""
Expense categorization using classification models.
"""
import numpy as np
import joblib
from sklearn.model_selection import train_test_split
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import classification_report, accuracy_score, confusion_matrix
from typing import Dict, Any, Optional

from backend.core.config import MODEL_DIR, RANDOM_STATE, TEST_SIZE


def train_categorizer(feature_matrix, labels, vectorizer) -> Dict[str, Any]:
    """
    Train multiple classification models, pick the best, return results.
    """
    # Train/test split with fallback for rare classes
    try:
        X_train, X_test, y_train, y_test = train_test_split(
            feature_matrix, labels, test_size=TEST_SIZE, random_state=RANDOM_STATE, stratify=labels
        )
    except ValueError:
        # Fallback if a class has < 2 members
        X_train, X_test, y_train, y_test = train_test_split(
            feature_matrix, labels, test_size=TEST_SIZE, random_state=RANDOM_STATE
        )

    models = {
        "Logistic Regression": LogisticRegression(
            max_iter=1000, random_state=RANDOM_STATE
        )
    }

    # Only run heavy models (Random Forest, XGBoost) if dataset is relatively small
    # This guarantees the pipeline finishes well under 20 seconds.
    if len(labels) <= 5000:
        models["Random Forest"] = RandomForestClassifier(
            n_estimators=100, random_state=RANDOM_STATE, n_jobs=-1
        )
        # Try XGBoost
        try:
            from xgboost import XGBClassifier
            from sklearn.preprocessing import LabelEncoder
            le = LabelEncoder()
            # Fit on all labels to avoid unseen class errors during transform
            le.fit(labels)
            y_train_encoded = le.transform(y_train)
            y_test_encoded = le.transform(y_test)
            xgb_model = XGBClassifier(
                n_estimators=100, random_state=RANDOM_STATE, use_label_encoder=False,
                eval_metric="mlogloss", verbosity=0
            )
            xgb_model.fit(X_train, y_train_encoded)
            xgb_preds = le.inverse_transform(xgb_model.predict(X_test))
            xgb_accuracy = accuracy_score(y_test, xgb_preds)
            models["XGBoost"] = (xgb_model, le, xgb_accuracy, xgb_preds)
        except ImportError:
            pass

    results = {}
    best_accuracy = 0
    best_model_name = None
    best_model = None
    best_preds = None

    for name, model in models.items():
        if isinstance(model, tuple):
            # XGBoost was already trained
            m, le, acc, preds = model
            results[name] = {"accuracy": float(acc)}
            if acc > best_accuracy:
                best_accuracy = acc
                best_model_name = name
                best_model = (m, le)
                best_preds = preds
        else:
            model.fit(X_train, y_train)
            preds = model.predict(X_test)
            acc = accuracy_score(y_test, preds)
            results[name] = {"accuracy": float(acc)}
            if acc > best_accuracy:
                best_accuracy = acc
                best_model_name = name
                best_model = model
                best_preds = preds

    # Classification report for best model
    report = classification_report(y_test, best_preds, output_dict=True, zero_division=0)
    cm = confusion_matrix(y_test, best_preds)
    classes = sorted(list(set(y_test)))

    # Save best model + vectorizer
    model_path = MODEL_DIR / "categorizer.pkl"
    joblib.dump({"model": best_model, "vectorizer": vectorizer}, model_path)

    return {
        "best_model": best_model_name,
        "best_accuracy": float(best_accuracy),
        "model_comparison": results,
        "classification_report": {
            k: v for k, v in report.items()
            if k not in ["accuracy", "macro avg", "weighted avg"]
        },
        "macro_avg": report.get("macro avg", {}),
        "weighted_avg": report.get("weighted avg", {}),
        "confusion_matrix": cm.tolist(),
        "class_labels": classes,
        "model_path": str(model_path),
    }


def predict_categories(df, vectorizer, model) -> np.ndarray:
    """Predict categories for new data using saved model."""
    from backend.ml.preprocessing import engineer_features

    tfidf_matrix = vectorizer.transform(df["description"].fillna(""))

    num_features = []
    for col in ["abs_amount", "weekday", "month", "is_weekend", "day_of_month"]:
        if col in df.columns:
            num_features.append(df[col].values.reshape(-1, 1))

    if num_features:
        num_matrix = np.hstack(num_features)
        from scipy.sparse import hstack as sparse_hstack
        feature_matrix = sparse_hstack([tfidf_matrix, num_matrix])
    else:
        feature_matrix = tfidf_matrix

    if isinstance(model, tuple):
        # XGBoost with LabelEncoder
        m, le = model
        preds_encoded = m.predict(feature_matrix)
        return le.inverse_transform(preds_encoded)
    else:
        return model.predict(feature_matrix)


def load_categorizer():
    """Load saved categorizer model."""
    model_path = MODEL_DIR / "categorizer.pkl"
    if model_path.exists():
        data = joblib.load(model_path)
        return data["model"], data["vectorizer"]
    return None, None
