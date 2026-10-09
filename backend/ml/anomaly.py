"""
Unusual-transaction review: a ranked list of expenses worth a second look.

This is NOT fraud detection. "Unusual" only means "far from this person's typical spending for the category".
Most unusual transactions are legitimate (a holiday, a new laptop, an annual bill). The output is a short
review queue: at most REVIEW_CAPACITY items, and only expenses at least MIN_DEVIATION_TO_FLAG robust deviations
above their category's typical amount, so the queue is shorter (or empty) when nothing really stands out.
It is never a claim about ground truth.

How a score is built (all explainable):
  * Category-relative deviation: the amount's distance from the category's typical amount, measured with the
    median and MAD (robust to the very outliers we are looking for) on a log scale (spending is right-skewed).
  * Isolation Forest: an unsupervised model that isolates points that are easy to separate from the rest.
Which of the two (or a blend) ships was decided by backend/ml/anomaly_eval.py on a labelled synthetic fixture:
the blend was not meaningfully better than the deviation score alone, so the simpler, fully explainable
deviation score is used. Isolation Forest stays here only for that comparison.
"""
from typing import Any

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest

from backend.core.config import MIN_DEVIATION_TO_FLAG, RANDOM_STATE, REVIEW_CAPACITY

MIN_EXPENSES = 20
MIN_CATEGORY_ROWS = 8  # smaller categories are compared with all spending instead
MIN_SCALE = 0.25  # floor for the spread on the log scale, so near-constant categories do not explode
MAX_Z = 6.0

METHODS = ("deviation", "isolation_forest", "blend")
METHOD = "deviation"  # chosen from the evaluation in anomaly_eval.py (see docs/model_card.md)
BLEND_WEIGHT_DEVIATION = 0.7

DISCLAIMER = (
    "Unusual does not mean fraudulent. These are expenses that stand out from your own pattern; "
    "most have an ordinary explanation. Confirm the ones you want to follow up on and dismiss the rest."
)


def _robust_stats(log_amount: pd.Series) -> tuple[float, float]:
    median = float(log_amount.median())
    mad = float((log_amount - median).abs().median())
    return median, max(1.4826 * mad, MIN_SCALE)


def deviation_scores(expenses: pd.DataFrame) -> pd.DataFrame:
    """Per-row category-relative z-score (high = unusually large for its category) and a typical amount."""
    log_amount = np.log(expenses["amount"].astype(float))
    global_median, global_scale = _robust_stats(log_amount)
    z = pd.Series(0.0, index=expenses.index)
    typical = pd.Series(np.exp(global_median), index=expenses.index)
    scope = pd.Series("all spending", index=expenses.index)
    for category, idx in expenses.groupby("effective_category").groups.items():
        if len(idx) >= MIN_CATEGORY_ROWS:
            median, scale = _robust_stats(log_amount.loc[idx])
            label = str(category)
        else:
            median, scale, label = global_median, global_scale, "all spending"
        z.loc[idx] = (log_amount.loc[idx] - median) / scale
        typical.loc[idx] = np.exp(median)
        scope.loc[idx] = label
    return pd.DataFrame({"z": z, "typical": typical, "scope": scope})


def isolation_scores(expenses: pd.DataFrame, z: pd.Series) -> pd.Series:
    """Isolation Forest outlier score in [0, 1] (percentile; 1 = most isolated). No fixed contamination rate."""
    dates = expenses["date"]
    features = np.column_stack(
        [np.log(expenses["amount"].astype(float)), z.to_numpy(), dates.dt.weekday.to_numpy(), dates.dt.day.to_numpy()]
    )
    forest = IsolationForest(n_estimators=200, contamination="auto", random_state=RANDOM_STATE, n_jobs=1).fit(features)
    isolated = -forest.score_samples(features)
    return pd.Series(isolated, index=expenses.index).rank(pct=True)


def combined_score(z: pd.Series, isolation: pd.Series | None, method: str) -> pd.Series:
    deviation = z.clip(lower=0, upper=MAX_Z) / MAX_Z
    if method == "deviation":
        return deviation
    if method == "isolation_forest":
        return isolation
    if method == "blend":
        return BLEND_WEIGHT_DEVIATION * deviation + (1 - BLEND_WEIGHT_DEVIATION) * isolation
    raise ValueError(f"unknown method {method}")


def _reason(amount: float, typical: float, scope: str) -> str:
    return f"Amount {amount:,.2f} is about {amount / typical:.1f}x the typical {scope} amount ({typical:,.2f})."


def rank_unusual(
    expenses: pd.DataFrame,
    method: str = METHOD,
    capacity: int = REVIEW_CAPACITY,
    min_z: float | None = MIN_DEVIATION_TO_FLAG,
) -> pd.DataFrame:
    """Score every expense and rank up to `capacity` of them. Needs date, amount (> 0) and effective_category.

    Only expenses with a deviation of at least `min_z` can be ranked (None disables the floor, which is used
    only to compare methods in the evaluation). Every expense still receives a score.
    """
    deviation = deviation_scores(expenses)
    # Isolation Forest is only fitted when a method needs it (the shipped method does not use it).
    isolation = isolation_scores(expenses, deviation["z"]) if method != "deviation" else None
    scored = pd.DataFrame(
        {
            "anomaly_score": combined_score(deviation["z"], isolation, method),
            "z": deviation["z"],
            "typical": deviation["typical"],
            "scope": deviation["scope"],
            "amount": expenses["amount"].astype(float),
        }
    )
    eligible = scored if min_z is None else scored[scored["z"] >= min_z]
    # The score is capped (MAX_Z), so ties among extreme rows are broken by the uncapped deviation, then the amount.
    order = eligible.sort_values(["anomaly_score", "z", "amount"], ascending=[False, False, False]).head(capacity)
    scored["anomaly_rank"] = pd.Series(range(1, len(order) + 1), index=order.index)
    scored["anomaly_reason"] = [
        _reason(r.amount, r.typical, r.scope) if pd.notna(scored.at[i, "anomaly_rank"]) else None
        for i, r in scored.iterrows()
    ]
    return scored[["anomaly_score", "anomaly_rank", "anomaly_reason"]]


def run_anomaly_detection(df: pd.DataFrame) -> dict[str, Any]:
    """Pipeline entry point. Returns a summary and, when completed, the per-row columns to store."""
    expenses = df[df["amount"] > 0]
    base = {
        "method": METHOD,
        "review_capacity": REVIEW_CAPACITY,
        "min_deviation": MIN_DEVIATION_TO_FLAG,
        "expenses_scanned": int(len(expenses)),
        "min_expenses": MIN_EXPENSES,
        "disclaimer": DISCLAIMER,
    }
    if len(expenses) < MIN_EXPENSES:
        return {
            **base,
            "status": "skipped",
            "reason": f"At least {MIN_EXPENSES} expenses are needed to tell what is unusual; this file has {len(expenses)}.",
            "row_columns": None,
        }
    ranked = rank_unusual(expenses)
    flagged = int(ranked["anomaly_rank"].notna().sum())
    return {
        **base,
        "status": "completed",
        "reason": None if flagged else "No expense stood out from your usual spending for its category.",
        "flagged": flagged,
        "row_columns": ranked,
    }
