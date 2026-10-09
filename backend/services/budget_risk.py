"""
Budget risk: current spending, projected month-end spending and a warning level per budgeted category.

Definitions (all assumptions are returned to the client so they can be shown):
  * "As of" date = the latest transaction date in the upload; "this month" = the calendar month of that date.
  * Spent so far = this month's expenses (amount > 0) per effective category, up to and including the as-of date.
  * Projected month-end = spent so far + the forecast total for the remaining days of the month
    x the category's share of spending in the last 90 days (it assumes the recent category mix continues).
  * If no forecast is available the projection is not extrapolated: projected = spent so far.
This is an estimate from past patterns, not financial advice.
"""
from typing import Any, Optional

import pandas as pd

SHARE_WINDOW_DAYS = 90
NEAR_LIMIT_FRACTION = 0.9
DISCLAIMER = "Estimates from your past spending pattern only. Not financial advice."

STATUS_OVER = "over_budget"  # already above the limit this month
STATUS_PROJECTED_OVER = "projected_over"  # on pace to go above the limit by month end
STATUS_NEAR = "near_limit"  # projected to reach at least 90% of the limit
STATUS_OK = "on_track"


def risk_status(limit: float, spent: float, projected: float) -> str:
    if spent > limit:
        return STATUS_OVER
    if projected > limit:
        return STATUS_PROJECTED_OVER
    if projected >= NEAR_LIMIT_FRACTION * limit:
        return STATUS_NEAR
    return STATUS_OK


def _remaining_forecast_total(forecast: Optional[dict], as_of: pd.Timestamp, month_end: pd.Timestamp) -> Optional[float]:
    if not forecast or forecast.get("status") != "completed":
        return None
    total = 0.0
    for point in forecast["forecast"]["daily"]:
        day = pd.Timestamp(point["date"])
        if as_of < day <= month_end:
            total += point["predicted_spending"]
    return total


def compute_budget_risk(
    transactions: pd.DataFrame, budgets: dict[str, float], forecast: Optional[dict]
) -> dict[str, Any]:
    """transactions needs columns: date (Timestamp), amount (canonical sign), effective_category."""
    base = {"disclaimer": DISCLAIMER, "categories": [], "totals": None, "as_of": None}
    dated = transactions.dropna(subset=["date"])
    if dated.empty:
        return {**base, "month": None, "remaining_days": None, "projection_method": "none"}

    as_of = dated["date"].max().normalize()
    month_start = as_of.replace(day=1)
    month_end = as_of + pd.offsets.MonthEnd(0)
    remaining_days = int((month_end - as_of).days)

    expenses = dated[dated["amount"] > 0]
    this_month = expenses[(expenses["date"] >= month_start) & (expenses["date"] < as_of + pd.Timedelta(days=1))]
    spent = this_month.groupby("effective_category")["amount"].sum()

    window = expenses[expenses["date"] > as_of - pd.Timedelta(days=SHARE_WINDOW_DAYS)]
    window_total = window["amount"].sum()
    share = (window.groupby("effective_category")["amount"].sum() / window_total) if window_total > 0 else pd.Series(dtype=float)

    remaining_total = _remaining_forecast_total(forecast, as_of, month_end)
    method = f"forecast:{forecast['method']}" if remaining_total is not None else "none"

    rows = []
    for category in sorted(budgets):
        limit = float(budgets[category])
        spent_so_far = float(spent.get(category, 0.0))
        extra = (remaining_total or 0.0) * float(share.get(category, 0.0))
        projected = spent_so_far + extra
        rows.append(
            {
                "category": category,
                "monthly_limit": round(limit, 2),
                "spent_so_far": round(spent_so_far, 2),
                "projected_month_end": round(projected, 2),
                "variance_current": round(limit - spent_so_far, 2),  # positive = room left now
                "variance_projected": round(limit - projected, 2),  # positive = projected to finish under the limit
                "percent_of_limit_spent": round(spent_so_far / limit * 100, 1),
                "status": risk_status(limit, spent_so_far, projected),
            }
        )

    return {
        **base,
        "as_of": as_of.strftime("%Y-%m-%d"),
        "month": month_start.strftime("%Y-%m"),
        "remaining_days": remaining_days,
        "projection_method": method,
        "assumptions": (
            "Projection = spent so far + forecast for the remaining days x each category's share of the last "
            f"{SHARE_WINDOW_DAYS} days of spending."
            if remaining_total is not None
            else "No forecast is available for this upload, so projected month-end equals spending so far."
        ),
        "categories": rows,
        "totals": {
            "monthly_limit": round(sum(r["monthly_limit"] for r in rows), 2),
            "spent_so_far": round(sum(r["spent_so_far"] for r in rows), 2),
            "projected_month_end": round(sum(r["projected_month_end"] for r in rows), 2),
            "categories_at_risk": sum(r["status"] in (STATUS_OVER, STATUS_PROJECTED_OVER) for r in rows),
        },
    }
