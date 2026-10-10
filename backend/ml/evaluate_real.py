"""
Real-world check of the shipped categorizer on the owner's own labelled transactions.

    python -m backend.ml.evaluate_real [path]        # default: data/private/real_labeled.csv

The input stays in data/private/ (ignored by git, excluded from Docker). Only AGGREGATE numbers are printed and
written (data/private/real_eval_report.json, also ignored): no description, merchant, amount, date or row-level
prediction ever appears in the output or in an error message. The categorizer is run exactly as the API runs it
(same text normalisation, direction token, unrecognised-text guard and threshold).

Scoring: a row the model leaves "Uncategorized" counts as a miss for accuracy and macro-F1 (the model did not name
the right category), and is also reported separately as "sent to review". Rows labelled Skip are not scored.
"""
import json
import sys
from datetime import date
from pathlib import Path

import pandas as pd
from sklearn.metrics import accuracy_score, f1_score

from backend.ml.categorizer import UNCATEGORIZED, load_categorizer
from backend.ml.rules import classify_with_rules
from backend.ml.text import direction_from_amount, is_blank, normalize_description

DEFAULT_INPUT = Path(__file__).resolve().parents[2] / "data" / "private" / "real_labeled.csv"
DEFAULT_REPORT = DEFAULT_INPUT.with_name("real_eval_report.json")
REQUIRED = ["date", "amount", "description", "true_category"]
MIN_ROWS, MAX_ROWS, MIN_CLASS_ROWS = 150, 300, 5


class InputProblem(Exception):
    """A problem with the file as a whole. Its message never contains row content."""


def _score(truth: pd.Series, predicted: pd.Series) -> dict:
    return {
        "accuracy": round(float(accuracy_score(truth, predicted)), 4),
        "macro_f1": round(float(f1_score(truth, predicted, labels=sorted(set(truth)), average="macro", zero_division=0)), 4),
    }


def evaluate(path: Path = DEFAULT_INPUT, categorizer=None, enforce_size: bool = True) -> dict:
    if not Path(path).exists():
        raise InputProblem("The labelled file does not exist. See data/private/README.txt.")
    df = pd.read_csv(path, dtype=str, keep_default_na=False)
    if list(df.columns) != REQUIRED:
        raise InputProblem(f"The file must have exactly these columns, in this order: {', '.join(REQUIRED)}.")
    categorizer = categorizer or load_categorizer()
    known = set(categorizer.categories)

    df["true_category"] = df["true_category"].str.strip()
    skipped = int((df["true_category"].str.lower() == "skip").sum())
    df = df[df["true_category"].str.lower() != "skip"].copy()
    amounts = pd.to_numeric(df["amount"], errors="coerce")
    bad_amount = int(amounts.isna().sum())
    unknown_label = int((~df["true_category"].isin(known)).sum())
    keep = amounts.notna() & df["true_category"].isin(known)
    df, amounts = df[keep].copy(), amounts[keep]
    if enforce_size and not (MIN_ROWS <= len(df) <= MAX_ROWS):
        raise InputProblem(
            f"{len(df)} usable labelled rows found; the check needs {MIN_ROWS}-{MAX_ROWS} "
            f"({skipped} skipped, {bad_amount} with an unreadable amount, {unknown_label} with a label that is not one of the {len(known)} categories)."
        )

    descriptions = df["description"].where(~df["description"].map(is_blank), None)
    predictions = categorizer.predict(descriptions, amounts)
    truth = df["true_category"].reset_index(drop=True)
    predicted = predictions["predicted_category"].reset_index(drop=True)
    reason = predictions["reason"].reset_index(drop=True)

    rule_predicted = pd.Series(
        [
            classify_with_rules(normalize_description(str(d), direction_from_amount(float(a)))) if d is not None else UNCATEGORIZED
            for d, a in zip(descriptions, amounts)
        ]
    )
    auto = predicted != UNCATEGORIZED
    per_class = {}
    for label, count in truth.value_counts().items():
        if count >= MIN_CLASS_ROWS:
            per_class[label] = {"rows": int(count), "recall": round(float(((predicted == label) & (truth == label)).sum() / count), 3)}

    report = {
        "measured_on": date.today().isoformat(),
        "what": "the shipped categorizer on one person's own labelled transactions (small, non-representative sample)",
        "model_version": categorizer.version,
        "confidence_threshold": categorizer.threshold,
        "rows_scored": int(len(truth)),
        "rows_skipped_by_owner": skipped,
        "rows_dropped_unreadable_amount": bad_amount,
        "rows_dropped_unknown_label": unknown_label,
        "model": _score(truth, predicted),
        "rules_baseline": _score(truth, rule_predicted),
        "auto_categorized_share": round(float(auto.mean()), 4),
        "sent_to_review_share": round(float((~auto).mean()), 4),
        "accuracy_of_auto_categorized": round(float((predicted[auto] == truth[auto]).mean()), 4) if auto.any() else None,
        "blocked_by_unrecognized_text_guard_share": round(float((reason == "unrecognized_text").mean()), 4),
        "per_class_recall_for_classes_with_5_or_more_rows": per_class,
        "note": "Aggregates only. Class names and counts are shown; no row content.",
    }
    return report


def main() -> None:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_INPUT
    try:
        report = evaluate(path)
    except InputProblem as problem:
        print(f"Cannot run the real-world check: {problem}")
        raise SystemExit(2)
    text = json.dumps(report, indent=2)
    DEFAULT_REPORT.write_text(text + "\n")
    print(text)
    print(f"\nWritten to {DEFAULT_REPORT.relative_to(DEFAULT_REPORT.parents[2])} (gitignored).")


if __name__ == "__main__":
    main()
