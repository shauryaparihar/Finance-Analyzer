import numpy as np
import pandas as pd
import pytest

from backend.core.config import REVIEW_CAPACITY
from backend.ml import anomaly as an
from backend.ml.anomaly_eval import evaluate, make_labelled_fixture, precision_recall_at_k


def _expenses(rows):
    return pd.DataFrame(
        [{"date": pd.Timestamp(d), "amount": a, "effective_category": c} for d, a, c in rows]
    )


def _baseline_rows(n=40):
    """Ordinary spending: groceries around 50-70, rent exactly 1500."""
    rng = np.random.default_rng(0)
    rows = [("2025-01-%02d" % (1 + i % 28), float(np.round(60 * np.exp(rng.normal(0, 0.15)), 2)), "Groceries") for i in range(n)]
    rows += [("2025-02-01", 1500.0, "Rent")] * 10
    return rows


def test_a_large_amount_is_flagged_for_its_category_but_normal_rent_is_not():
    data = _expenses(_baseline_rows() + [("2025-03-05", 600.0, "Groceries")])
    ranked = an.rank_unusual(data)
    spike = ranked.loc[ranked.index[-1]]
    assert spike["anomaly_rank"] == 1
    assert "Groceries" in spike["anomaly_reason"] and "x the typical" in spike["anomaly_reason"]
    rent_rows = data.index[data["effective_category"] == "Rent"]
    assert ranked.loc[rent_rows, "anomaly_score"].max() < 0.1  # 1500 is ordinary for Rent, though huge for Groceries


def test_the_review_list_is_ordered_by_rank_and_score():
    spikes = [("2025-03-01", 300.0, "Groceries"), ("2025-03-02", 900.0, "Groceries"), ("2025-03-03", 600.0, "Groceries")]
    ranked = an.rank_unusual(_expenses(_baseline_rows() + spikes))
    queue = ranked.dropna(subset=["anomaly_rank"]).sort_values("anomaly_rank")
    assert list(queue["anomaly_rank"]) == list(range(1, len(queue) + 1))
    assert list(queue["anomaly_score"]) == sorted(queue["anomaly_score"], reverse=True)
    top_amounts = _expenses(_baseline_rows() + spikes).loc[queue.index[:3], "amount"]
    assert list(top_amounts) == [900.0, 600.0, 300.0]  # equally capped scores are ordered by the uncapped deviation


@pytest.mark.parametrize("capacity", [1, 3, REVIEW_CAPACITY])
def test_the_review_capacity_is_enforced(capacity):
    data = _expenses(_baseline_rows() + [("2025-03-%02d" % d, 400.0 + d, "Groceries") for d in range(1, 16)])
    ranked = an.rank_unusual(data, capacity=capacity)
    assert ranked["anomaly_rank"].notna().sum() == capacity
    assert ranked["anomaly_reason"].notna().sum() == capacity  # reasons only for ranked rows
    assert ranked["anomaly_score"].notna().all()  # every expense still gets a score


def test_the_default_capacity_is_the_documented_one():
    data = _expenses(_baseline_rows() + [("2025-03-%02d" % d, 400.0 + d, "Groceries") for d in range(1, 16)])
    assert an.rank_unusual(data)["anomaly_rank"].notna().sum() == REVIEW_CAPACITY == 10


def test_small_categories_are_compared_with_all_spending_and_say_so():
    rows = _baseline_rows() + [("2025-03-01", 700.0, "Pets"), ("2025-03-02", 5.0, "Pets")]
    data = _expenses(rows)
    scored = an.deviation_scores(data)
    pets = data.index[data["effective_category"] == "Pets"]
    assert (scored.loc[pets, "scope"] == "all spending").all()
    assert "all spending" in an.rank_unusual(data).loc[pets[0], "anomaly_reason"]


def test_too_few_expenses_are_skipped_with_a_reason_not_an_error():
    df = _expenses([("2025-01-01", 10.0, "Groceries")] * 5)
    result = an.run_anomaly_detection(df)
    assert result["status"] == "skipped" and "20" in result["reason"] and result["row_columns"] is None


def test_income_rows_are_never_ranked():
    df = _expenses(_baseline_rows())
    df.loc[len(df)] = [pd.Timestamp("2025-03-01"), -9000.0, "Income"]
    result = an.run_anomaly_detection(df)
    assert len(result["row_columns"]) == len(df) - 1 and result["expenses_scanned"] == len(df) - 1


def test_the_summary_makes_no_fraud_claim_and_states_the_limits():
    result = an.run_anomaly_detection(_expenses(_baseline_rows()))
    assert result["status"] == "completed" and result["review_capacity"] == 10
    assert "does not mean fraudulent" in result["disclaimer"]
    assert "fraud" not in an.__doc__.split("This is NOT fraud detection")[0].lower()


def test_precision_and_recall_at_k_on_a_known_ranking():
    ranked = [True, False, True, True, False, False]
    assert precision_recall_at_k(ranked, total_true=4, k=3) == (pytest.approx(2 / 3), pytest.approx(2 / 4))
    assert precision_recall_at_k(ranked, total_true=4, k=1) == (1.0, 0.25)
    assert precision_recall_at_k([False, False], total_true=0, k=2) == (0.0, 0.0)


def test_the_labelled_fixture_contains_exactly_the_requested_injected_rows():
    data = make_labelled_fixture(seed=3, n_normal=200, n_anomalies=7)
    assert int(data["is_injected"].sum()) == 7 and len(data) == 207
    pd.testing.assert_frame_equal(data, make_labelled_fixture(seed=3, n_normal=200, n_anomalies=7))


def test_the_shipped_method_finds_most_injected_spikes_and_beats_isolation_forest_alone():
    seeds = range(8)
    deviation = evaluate("deviation", seeds=seeds)
    isolation = evaluate("isolation_forest", seeds=seeds)
    assert deviation["precision_at_k_mean"] >= 0.65 and deviation["recall_at_k_mean"] >= 0.65
    assert deviation["precision_at_k_mean"] > isolation["precision_at_k_mean"]
    assert an.METHOD == "deviation"
