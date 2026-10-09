"""
Offline, deterministic training of the transaction categorizer.

    python -m backend.ml.prepare_training_data     # download the dataset once
    python -m backend.ml.train_categorizer         # train, evaluate, write the artifact

What it does:
  1. Loads the synthetic training data and removes exact duplicate rows.
  2. Splits by merchant group (never row by row), so the same merchant never appears on both sides. One group
     fold is held out as the TEST set; the other folds are the development set.
  3. Runs grouped cross-validation on the development set. Its pooled out-of-fold predictions are used to pick
     the confidence threshold (one validation fold alone was too unstable: a single big ambiguous merchant
     group can swing it by several points) and to report how much scores vary between folds.
  4. Trains the shipped model on the whole development set and scores it, and a transparent keyword baseline,
     on the untouched test groups.
  5. Saves one artifact plus a metadata file with metrics, versions, settings and a checksum.

All results are on SYNTHETIC data. They measure agreement with the data generator, not real-world accuracy.
"""
import argparse
import hashlib
import json
import platform
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import scipy
import sklearn
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix, f1_score
from sklearn.model_selection import StratifiedGroupKFold
from sklearn.pipeline import FeatureUnion, Pipeline

from backend.core.config import ARTIFACT_DIR, RANDOM_STATE
from backend.ml.categorizer import METADATA_FILE, MODEL_FILE, UNCATEGORIZED, file_sha256
from backend.ml.prepare_training_data import DATASET_PATH, DATASET_URL
from backend.ml.rules import classify_with_rules
from backend.ml.text import is_blank, merchant_group, normalize_description

TARGET_ACCEPTED_ACCURACY = 0.95  # the review threshold must make confident predictions at least this accurate (validation)
CANDIDATE_THRESHOLDS = [round(t, 2) for t in np.arange(0.30, 0.96, 0.05)]
PROTOCOL_VERSION = "grouped-cv-v1"  # bump when the evaluation/threshold procedure changes
SPLIT_FOLDS = 7  # one fold is the test set (~14%); the other six are the development set

FEATURE_CONFIG = {
    "text": "normalized description (lowercase, digits/codes/punctuation removed) with a debit/credit direction token",
    "word_tfidf": {"ngram_range": [1, 2], "min_df": 2, "sublinear_tf": True},
    "char_tfidf": {"analyzer": "char_wb", "ngram_range": [3, 5], "min_df": 3, "sublinear_tf": True},
    "classifier": {"name": "LogisticRegression", "C": 10.0, "max_iter": 1000},
    "amount_used_as_feature": False,
}


def build_pipeline() -> Pipeline:
    cfg = FEATURE_CONFIG
    return Pipeline(
        [
            (
                "features",
                FeatureUnion(
                    [
                        ("word", TfidfVectorizer(ngram_range=(1, 2), min_df=2, sublinear_tf=True)),
                        ("char", TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), min_df=3, sublinear_tf=True)),
                    ]
                ),
            ),
            ("model", LogisticRegression(C=cfg["classifier"]["C"], max_iter=cfg["classifier"]["max_iter"], random_state=RANDOM_STATE)),
        ]
    )


def prepare_frame(raw: pd.DataFrame) -> pd.DataFrame:
    """Clean the raw dataset: drop missing/duplicate rows, add normalized text and merchant group."""
    df = raw.dropna(subset=["description", "category"])
    df = df[~df["description"].map(is_blank)].drop_duplicates().reset_index(drop=True)
    df["text"] = [normalize_description(d) for d in df["description"]]
    df["group"] = [merchant_group(d) for d in df["description"]]
    return df


def split_by_group(df: pd.DataFrame, seed: int = RANDOM_STATE) -> dict:
    """Index arrays with no merchant group shared between the test set and any development fold, or between folds."""
    splitter = StratifiedGroupKFold(n_splits=SPLIT_FOLDS, shuffle=True, random_state=seed)
    folds = [np.sort(test_idx) for _, test_idx in splitter.split(df["text"], df["category"], groups=df["group"])]
    return {"test": folds[0], "cv_folds": folds[1:], "development": np.sort(np.concatenate(folds[1:]))}


def choose_threshold(confidence: np.ndarray, correct: np.ndarray) -> float:
    """Lowest threshold whose accepted predictions reach the target accuracy.

    If the target is unreachable (for example because of genuinely ambiguous merchants), use the threshold with
    the best accepted accuracy among those that still auto-categorize at least half of the rows.
    """
    fallback, fallback_accuracy = CANDIDATE_THRESHOLDS[0], -1.0
    for threshold in CANDIDATE_THRESHOLDS:
        accepted = confidence >= threshold
        if accepted.sum() == 0:
            continue
        accuracy = float(correct[accepted].mean())
        if accuracy >= TARGET_ACCEPTED_ACCURACY:
            return threshold
        if accepted.mean() >= 0.5 and accuracy > fallback_accuracy:
            fallback, fallback_accuracy = threshold, accuracy
    return fallback


def _report(y_true, y_pred, labels) -> dict:
    report = classification_report(y_true, y_pred, labels=labels, output_dict=True, zero_division=0)
    return {
        "accuracy_secondary": float(accuracy_score(y_true, y_pred)),
        "macro_f1": float(f1_score(y_true, y_pred, labels=labels, average="macro", zero_division=0)),
        "weighted_f1": float(f1_score(y_true, y_pred, labels=labels, average="weighted", zero_division=0)),
        "per_class": {k: {m: float(v) for m, v in report[k].items()} for k in labels},
        "confusion_matrix": confusion_matrix(y_true, y_pred, labels=labels).tolist(),
        "labels": list(labels),
    }


def train_and_evaluate(raw: pd.DataFrame, seed: int = RANDOM_STATE) -> tuple[Pipeline, dict]:
    """Cross-validate on development groups, fit the final model, report on held-out test groups."""
    df = prepare_frame(raw)
    splits = split_by_group(df, seed)
    labels = sorted(df["category"].unique())
    texts, categories = df["text"], df["category"]

    # Grouped cross-validation on the development set: out-of-fold predictions for threshold choice and spread.
    oof_confidence, oof_correct, fold_macro_f1 = [], [], []
    for i, held_out in enumerate(splits["cv_folds"]):
        train_idx = np.concatenate([f for j, f in enumerate(splits["cv_folds"]) if j != i])
        fold_model = build_pipeline().fit(texts.iloc[train_idx], categories.iloc[train_idx])
        proba = fold_model.predict_proba(texts.iloc[held_out])
        pred = fold_model.classes_[proba.argmax(axis=1)]
        truth = categories.iloc[held_out].to_numpy()
        oof_confidence.append(proba.max(axis=1))
        oof_correct.append(pred == truth)
        fold_macro_f1.append(float(f1_score(truth, pred, labels=labels, average="macro", zero_division=0)))
    oof_confidence, oof_correct = np.concatenate(oof_confidence), np.concatenate(oof_correct)
    threshold = choose_threshold(oof_confidence, oof_correct)
    accepted_oof = oof_confidence >= threshold

    # Final model: trained on the whole development set, scored once on the untouched test groups.
    dev, test = df.iloc[splits["development"]], df.iloc[splits["test"]]
    pipeline = build_pipeline()
    pipeline.fit(dev["text"], dev["category"])

    test_proba = pipeline.predict_proba(test["text"])
    test_pred = pipeline.classes_[test_proba.argmax(axis=1)]
    accepted = test_proba.max(axis=1) >= threshold
    correct = test_pred == test["category"].to_numpy()

    rules_pred = np.array([classify_with_rules(t) for t in test["text"]])
    rules_covered = rules_pred != UNCATEGORIZED

    results = {
        "split": {
            "method": (
                f"StratifiedGroupKFold(n_splits={SPLIT_FOLDS}, shuffle=True, random_state={seed}) on merchant group; "
                "1 fold = test, 6 folds = development (grouped cross-validation)"
            ),
            "rows": {"development": len(dev), "test": len(test)},
            "groups": {"development": int(dev["group"].nunique()), "test": int(test["group"].nunique())},
            "group_overlap_development_test": len(set(dev["group"]) & set(test["group"])),
        },
        "cross_validation": {
            "folds": len(fold_macro_f1),
            "macro_f1_per_fold": fold_macro_f1,
            "macro_f1_mean": float(np.mean(fold_macro_f1)),
            "macro_f1_std": float(np.std(fold_macro_f1)),
            "pooled_out_of_fold_accuracy": float(oof_correct.mean()),
            "pooled_coverage_at_threshold": float(accepted_oof.mean()),
            "pooled_accuracy_at_threshold": float(oof_correct[accepted_oof].mean()) if accepted_oof.any() else None,
        },
        "confidence_threshold": threshold,
        "threshold_selection": (
            f"lowest threshold on pooled out-of-fold predictions where accepted predictions reach "
            f"{TARGET_ACCEPTED_ACCURACY:.0%} accuracy; if unreachable, best accepted accuracy with at least 50% coverage"
        ),
        "model_test": _report(test["category"], test_pred, labels),
        "model_test_at_threshold": {
            "coverage_auto_categorized": float(accepted.mean()),
            "sent_to_review": float(1 - accepted.mean()),
            "accuracy_of_auto_categorized": float(correct[accepted].mean()) if accepted.any() else None,
        },
        "rules_baseline_test": {
            **_report(test["category"], rules_pred, labels),
            "coverage": float(rules_covered.mean()),
            "accuracy_when_covered": float((rules_pred[rules_covered] == test["category"].to_numpy()[rules_covered]).mean())
            if rules_covered.any()
            else None,
            "note": "rows the rules cannot categorize count as wrong in macro_f1/accuracy_secondary",
        },
        "dataset_rows_after_dedup": len(df),
    }
    return pipeline, results


def build_metadata(pipeline: Pipeline, results: dict, dataset_path: Path, rows_raw: int) -> dict:
    dataset_sha = file_sha256(dataset_path)
    identity = json.dumps({"data": dataset_sha, "features": FEATURE_CONFIG, "seed": RANDOM_STATE, "folds": SPLIT_FOLDS, "protocol": PROTOCOL_VERSION}, sort_keys=True)
    version = "tfidf-lr-" + hashlib.sha256(identity.encode()).hexdigest()[:8]
    return {
        "model_version": version,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "training_data": {
            "source": "DoDataThings/us-bank-transaction-categories-v2 (Hugging Face)",
            "url": DATASET_URL,
            "license": "MIT (per dataset card)",
            "synthetic": True,
            "file_sha256": dataset_sha,
            "rows_raw": rows_raw,
            "rows_after_dedup": results["dataset_rows_after_dedup"],
            "classes": [str(c) for c in pipeline.classes_],
        },
        "feature_config": FEATURE_CONFIG,
        "random_state": RANDOM_STATE,
        "split": results["split"],
        "confidence_threshold": results["confidence_threshold"],
        "threshold_selection": results["threshold_selection"],
        "metrics": {
            "note": "SYNTHETIC data: agreement with the dataset generator, not real-world accuracy",
            "cross_validation": results["cross_validation"],
            "model_test": results["model_test"],
            "model_test_at_threshold": results["model_test_at_threshold"],
            "rules_baseline_test": results["rules_baseline_test"],
        },
        "library_versions": {
            "python": platform.python_version(),
            "scikit-learn": sklearn.__version__,
            "numpy": np.__version__,
            "pandas": pd.__version__,
            "scipy": scipy.__version__,
            "joblib": joblib.__version__,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data", type=Path, default=DATASET_PATH)
    parser.add_argument("--out", type=Path, default=ARTIFACT_DIR)
    args = parser.parse_args()

    raw = pd.read_csv(args.data)
    pipeline, results = train_and_evaluate(raw)
    metadata = build_metadata(pipeline, results, args.data, rows_raw=len(raw))

    args.out.mkdir(parents=True, exist_ok=True)
    model_path = args.out / MODEL_FILE
    joblib.dump(pipeline, model_path, compress=3)
    metadata["artifact_file"] = MODEL_FILE
    metadata["artifact_sha256"] = file_sha256(model_path)
    (args.out / METADATA_FILE).write_text(json.dumps(metadata, indent=2))

    m, t, r, cv = results["model_test"], results["model_test_at_threshold"], results["rules_baseline_test"], results["cross_validation"]
    print(f"model_version        {metadata['model_version']}")
    print(f"rows after dedup     {results['dataset_rows_after_dedup']}  split {results['split']['rows']}")
    print(f"group overlap        development/test={results['split']['group_overlap_development_test']}")
    print(f"CV macro F1          mean {cv['macro_f1_mean']:.3f} std {cv['macro_f1_std']:.3f}  per fold {[round(x, 3) for x in cv['macro_f1_per_fold']]}")
    print(f"confidence threshold {results['confidence_threshold']}  (pooled OOF: coverage {cv['pooled_coverage_at_threshold']:.1%}, accepted accuracy {cv['pooled_accuracy_at_threshold']:.3f})")
    print(f"MODEL  test macro F1 {m['macro_f1']:.3f}  weighted F1 {m['weighted_f1']:.3f}  (accuracy {m['accuracy_secondary']:.3f})")
    print(f"       auto-categorized {t['coverage_auto_categorized']:.1%}  review {t['sent_to_review']:.1%}  accuracy of auto {t['accuracy_of_auto_categorized']:.3f}")
    print(f"RULES  test macro F1 {r['macro_f1']:.3f}  weighted F1 {r['weighted_f1']:.3f}  coverage {r['coverage']:.1%}  accuracy when covered {r['accuracy_when_covered']:.3f}")
    print(f"artifact             {model_path}  ({model_path.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
