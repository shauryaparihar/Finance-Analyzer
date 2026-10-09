import pandas as pd
import pytest

from backend.services.budget_risk import (
    STATUS_NEAR,
    STATUS_OK,
    STATUS_OVER,
    STATUS_PROJECTED_OVER,
    compute_budget_risk,
    risk_status,
)


def _tx(rows):
    return pd.DataFrame(
        [{"date": pd.Timestamp(d), "amount": a, "effective_category": c} for d, a, c in rows],
        columns=["date", "amount", "effective_category"],
    )


def _forecast(per_day, as_of="2025-03-10", days=31, method="seasonal_naive"):
    start = pd.Timestamp(as_of) + pd.Timedelta(days=1)
    daily = [
        {"date": (start + pd.Timedelta(days=i)).strftime("%Y-%m-%d"), "predicted_spending": per_day} for i in range(days)
    ]
    return {"status": "completed", "method": method, "forecast": {"daily": daily}}


FIXTURE = _tx(
    [
        ("2025-02-20", 100.0, "Dining"),  # earlier month: counts for the category mix, not for "spent so far"
        ("2025-03-02", 30.0, "Dining"),
        ("2025-03-05", 20.0, "Dining"),
        ("2025-03-06", 50.0, "Groceries"),
        ("2025-03-08", -2000.0, "Income"),  # money in: never counted as spending
        ("2025-03-10", 100.0, "Groceries"),
    ]
)


def test_status_boundaries():
    assert risk_status(limit=100, spent=101, projected=101) == STATUS_OVER
    assert risk_status(limit=100, spent=50, projected=100.01) == STATUS_PROJECTED_OVER
    assert risk_status(limit=100, spent=50, projected=100.0) == STATUS_NEAR
    assert risk_status(limit=100, spent=50, projected=90.0) == STATUS_NEAR
    assert risk_status(limit=100, spent=50, projected=89.99) == STATUS_OK
    assert risk_status(limit=100, spent=100, projected=100) == STATUS_NEAR  # exactly at the limit is not over it


def test_spent_so_far_reconciles_with_the_transactions_of_the_month():
    result = compute_budget_risk(FIXTURE, {"Dining": 100.0, "Groceries": 400.0}, None)
    by_category = {row["category"]: row for row in result["categories"]}
    assert by_category["Dining"]["spent_so_far"] == 50.0  # 30 + 20, not the February 100
    assert by_category["Groceries"]["spent_so_far"] == 150.0  # 50 + 100
    assert result["month"] == "2025-03" and result["as_of"] == "2025-03-10" and result["remaining_days"] == 21
    assert result["totals"]["spent_so_far"] == 200.0


def test_variance_calculation_on_a_small_fixture():
    forecast = _forecast(per_day=10.0)  # remaining March days (11..31) = 21 days -> 210 total
    result = compute_budget_risk(FIXTURE, {"Dining": 100.0, "Groceries": 400.0}, forecast)
    rows = {r["category"]: r for r in result["categories"]}
    # Spending in the last 90 days (expenses only): Dining 150, Groceries 150 -> each has a 50% share.
    assert rows["Dining"]["projected_month_end"] == pytest.approx(50 + 210 * 0.5)  # 155
    assert rows["Dining"]["variance_projected"] == pytest.approx(100 - 155)
    assert rows["Dining"]["variance_current"] == pytest.approx(100 - 50)
    assert rows["Dining"]["status"] == STATUS_PROJECTED_OVER
    assert rows["Groceries"]["projected_month_end"] == pytest.approx(150 + 105)  # 255
    assert rows["Groceries"]["status"] == STATUS_OK  # 255 of 400 is below 90%
    assert result["projection_method"] == "forecast:seasonal_naive"
    assert result["totals"]["categories_at_risk"] == 1


def test_only_forecast_days_inside_the_month_are_used():
    result_short = compute_budget_risk(FIXTURE, {"Dining": 1000.0}, _forecast(per_day=10.0, days=5))
    result_full = compute_budget_risk(FIXTURE, {"Dining": 1000.0}, _forecast(per_day=10.0, days=31))
    assert result_short["categories"][0]["projected_month_end"] == pytest.approx(50 + 5 * 10 * 0.5)
    assert result_full["categories"][0]["projected_month_end"] == pytest.approx(50 + 21 * 10 * 0.5)  # April days ignored


def test_without_a_forecast_nothing_is_extrapolated_and_the_result_says_so():
    for forecast in (None, {"status": "skipped", "reason": "too short"}):
        result = compute_budget_risk(FIXTURE, {"Dining": 100.0}, forecast)
        row = result["categories"][0]
        assert row["projected_month_end"] == row["spent_so_far"] == 50.0
        assert result["projection_method"] == "none" and "No forecast" in result["assumptions"]


def test_a_budgeted_category_with_no_spending_is_reported_not_dropped():
    result = compute_budget_risk(FIXTURE, {"Travel": 500.0}, _forecast(per_day=10.0))
    row = result["categories"][0]
    assert row["spent_so_far"] == 0.0 and row["projected_month_end"] == 0.0 and row["status"] == STATUS_OK


def test_already_over_budget_is_flagged_as_over():
    result = compute_budget_risk(FIXTURE, {"Dining": 40.0}, None)
    assert result["categories"][0]["status"] == STATUS_OVER and result["categories"][0]["percent_of_limit_spent"] == 125.0


def test_empty_transactions_do_not_crash():
    result = compute_budget_risk(_tx([]), {"Dining": 100.0}, None)
    assert result["categories"] == [] and result["projection_method"] == "none"
