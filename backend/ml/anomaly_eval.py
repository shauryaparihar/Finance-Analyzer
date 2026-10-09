"""
Evaluate the unusual-transaction ranking on a LABELLED SYNTHETIC fixture.

    python -m backend.ml.anomaly_eval

The fixture builds realistic category spending and injects spikes (4-12x the category's typical amount) that we
know about. This measures whether the ranking surfaces the injected spikes in its top K. The spikes follow the
same "unusually large amount" idea the method looks for, so the numbers are optimistic: they show the ranking
works as designed, not that it finds real-world problems.
"""
import numpy as np
import pandas as pd

from backend.core.config import MIN_DEVIATION_TO_FLAG, REVIEW_CAPACITY
from backend.ml.anomaly import METHODS, rank_unusual

# category -> (typical amount, spread of log-amount)
CATEGORIES = {
    "Groceries": (60.0, 0.35),
    "Restaurants": (25.0, 0.5),
    "Utilities": (120.0, 0.25),
    "Transportation": (35.0, 0.6),
    "Shopping": (80.0, 0.8),
    "Subscription": (15.0, 0.1),
    "Healthcare": (90.0, 0.7),
}


def make_labelled_fixture(seed: int, n_normal: int = 900, n_anomalies: int = 10) -> pd.DataFrame:
    """Rows with date, amount, effective_category and is_injected (the ground truth)."""
    rng = np.random.default_rng(seed)
    names = list(CATEGORIES)
    start = pd.Timestamp("2025-01-01")

    def rows(n, injected):
        picked = rng.choice(names, size=n)
        typical = np.array([CATEGORIES[c][0] for c in picked])
        spread = np.array([CATEGORIES[c][1] for c in picked])
        amount = typical * np.exp(rng.normal(0, spread))
        if injected:
            amount = typical * rng.uniform(4, 12, size=n)
        return pd.DataFrame(
            {
                "date": start + pd.to_timedelta(rng.integers(0, 180, size=n), unit="D"),
                "amount": np.round(amount, 2),
                "effective_category": picked,
                "is_injected": injected,
            }
        )

    return pd.concat([rows(n_normal, False), rows(n_anomalies, True)], ignore_index=True)


def precision_recall_at_k(ranked_is_true: list[bool], total_true: int, k: int) -> tuple[float, float]:
    """Precision@K = share of the items shown (at most K) that are true anomalies; recall@K = share of all true
    anomalies that were shown. If fewer than K items are shown, precision is over the items actually shown."""
    top = ranked_is_true[:k]
    hits = sum(top)
    return (hits / len(top) if top else 0.0), (hits / total_true if total_true else 0.0)


def evaluate(
    method: str, seeds=range(20), k: int = REVIEW_CAPACITY, n_anomalies: int = 10, min_z: float | None = None
) -> dict:
    """Mean precision@K / recall@K over labelled fixtures. min_z=None compares methods with no minimum deviation."""
    precisions, recalls, sizes = [], [], []
    for seed in seeds:
        data = make_labelled_fixture(seed, n_anomalies=n_anomalies)
        ranked = rank_unusual(data, method=method, capacity=k, min_z=min_z)
        order = ranked.dropna(subset=["anomaly_rank"]).sort_values("anomaly_rank").index
        precision, recall = precision_recall_at_k(list(data.loc[order, "is_injected"]), int(data["is_injected"].sum()), k)
        precisions.append(precision)
        recalls.append(recall)
        sizes.append(len(order))
    return {
        "method": method,
        "k": k,
        "min_z": min_z,
        "fixtures": len(list(seeds)),
        "injected_per_fixture": n_anomalies,
        "precision_at_k_mean": float(np.mean(precisions)),
        "precision_at_k_std": float(np.std(precisions)),
        "recall_at_k_mean": float(np.mean(recalls)),
        "recall_at_k_std": float(np.std(recalls)),
        "queue_size_mean": float(np.mean(sizes)),
    }


def false_alarms_on_clean_data(min_z: float | None, seeds=range(20)) -> float:
    """Average number of items flagged when nothing was injected, i.e. every flagged item is a false alarm."""
    flagged = [
        int(rank_unusual(make_labelled_fixture(seed, n_anomalies=0), min_z=min_z)["anomaly_rank"].notna().sum())
        for seed in seeds
    ]
    return float(np.mean(flagged))


def main() -> None:
    print(f"Labelled synthetic fixtures: 900 normal rows + 10 injected spikes each, K={REVIEW_CAPACITY}, 20 seeds")
    print("A) method comparison, no minimum deviation (queue always filled to K)")
    for method in METHODS:
        r = evaluate(method)
        print(
            f"  {method:17s} precision@{r['k']} {r['precision_at_k_mean']:.3f} +/- {r['precision_at_k_std']:.3f}   "
            f"recall@{r['k']} {r['recall_at_k_mean']:.3f} +/- {r['recall_at_k_std']:.3f}"
        )
    print("B) minimum deviation for the shipped method (deviation): precision of items shown, recall, queue size,")
    print("   and items flagged on 20 fixtures with NO injected spikes (all false alarms)")
    for min_z in (None, 2.0, 2.5, MIN_DEVIATION_TO_FLAG, 4.0):
        r = evaluate("deviation", min_z=min_z)
        label = "none" if min_z is None else f"{min_z:.1f}"
        marker = "  <- shipped" if min_z == MIN_DEVIATION_TO_FLAG else ""
        print(
            f"  min deviation {label:>4}: precision {r['precision_at_k_mean']:.3f}  recall {r['recall_at_k_mean']:.3f}  "
            f"queue {r['queue_size_mean']:.1f}  false alarms on clean data {false_alarms_on_clean_data(min_z):.1f}{marker}"
        )


if __name__ == "__main__":
    main()
