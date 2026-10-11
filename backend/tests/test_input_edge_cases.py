"""Inputs that are inside the upload limits but would have hurt the server or the results."""
import io
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from backend.api.errors import AppError
from backend.ml import forecast as fc
from backend.tests.conftest import register_and_login
from backend.tests.test_end_to_end import real_client  # noqa: F401  (fixture)
from backend.utils.csv_ingest import MAX_ABS_AMOUNT, MIN_DATE, validate_and_clean_csv


def _csv(dates, amounts, desc=None):
    desc = desc or ["SHOP"] * len(dates)
    return pd.DataFrame({"date": dates, "amount": amounts, "description": desc}).to_csv(index=False).encode()


def _clean(content, **kw):
    return validate_and_clean_csv(content, "x.csv", "expenses_positive", max_bytes=5 * 1024 * 1024, max_rows=50_000, max_invalid_share=kw.get("share", 0.2))


def test_infinite_and_absurd_amounts_count_as_invalid_rows_not_data():
    dates = [f"2025-01-{d:02d}" for d in range(1, 29)] * 2
    amounts = [10.0] * 50 + ["inf", "-inf", 1e300, -1e300, 5e12, 7.5]
    result = _clean(_csv(dates, amounts))
    assert len(result.df) == 51 and result.rows_dropped == 5
    assert result.df["amount"].abs().max() <= MAX_ABS_AMOUNT


def test_dates_far_in_the_past_or_future_count_as_invalid_rows():
    dates = ["2025-03-01"] * 55 + ["1700-01-01", "2999-01-01", "1969-12-31", "2200-01-01", "1999-05-05"]
    result = _clean(_csv(dates, [5.0] * 60))
    assert result.rows_dropped == 4 and len(result.df) == 56
    assert result.df["date"].min() >= pd.Timestamp(MIN_DATE)


def test_a_file_that_is_mostly_implausible_is_refused_with_a_clear_message():
    with pytest.raises(AppError) as refused:
        _clean(_csv(["1700-01-01"] * 30 + ["2025-01-01"] * 10, [5.0] * 40))
    assert refused.value.code == "UPLOAD_TOO_MANY_INVALID_ROWS"


def test_the_forecast_uses_at_most_the_last_five_years_so_a_long_series_cannot_exhaust_the_server():
    start = date(1995, 1, 1)
    days = 365 * 28
    frame = pd.DataFrame({"date": pd.to_datetime([start + timedelta(days=i) for i in range(days)]), "amount": np.full(days, 10.0)})
    series = fc.build_daily_series(frame)
    assert len(series) == fc.MAX_HISTORY_DAYS
    assert series.index[-1] == pd.Timestamp(start + timedelta(days=days - 1))  # the most recent days are kept


def test_a_short_series_is_not_cut():
    frame = pd.DataFrame({"date": pd.date_range("2025-01-01", periods=200), "amount": np.full(200, 10.0)})
    assert len(fc.build_daily_series(frame)) == 200


def test_a_backtest_window_with_no_spending_gives_no_percentage_instead_of_a_warning_or_a_crash():
    import warnings

    with warnings.catch_warnings():
        warnings.simplefilter("error")
        value = fc._window_total_error_pct([np.zeros(14), np.zeros(14)], [np.ones(14), np.ones(14)])
    assert np.isnan(value)


def test_a_sparse_file_goes_through_the_whole_api_and_every_screen_still_loads(real_client):  # noqa: F811
    client = real_client
    headers = register_and_login(client)
    # one expense a month for a year: some backtest windows contain no spending at all
    months = pd.date_range("2025-01-01", periods=12, freq="MS")
    content = _csv([d.strftime("%Y-%m-%d") for d in months] * 3, [100.0] * 12 + [20.0] * 12 + [5.0] * 12)
    response = client.post("/api/uploads", headers=headers, files={"file": ("sparse.csv", io.BytesIO(content), "text/csv")})
    assert response.status_code == 202, response.text
    upload_id = response.json()["upload_id"]
    assert client.get(f"/api/uploads/{upload_id}/status", headers=headers).json()["status"] in {"completed", "partial"}
    for path in ("summary", "forecast", "anomalies", "transactions", "budget-risk"):
        assert client.get(f"/api/uploads/{upload_id}/{path}", headers=headers).status_code == 200, path
