import numpy as np
import pandas as pd
import pytest

from backend.core.config import PREDICTION_DAYS
from backend.ml import forecast as fc


def _transactions(values, start="2025-01-01"):
    """One expense row per day for the given daily totals (zero days get no row)."""
    dates = pd.date_range(start, periods=len(values), freq="D")
    rows = [{"date": d, "amount": float(v)} for d, v in zip(dates, values) if v > 0]
    return pd.DataFrame(rows)


def _weekly_pattern(days):
    return np.array([10, 20, 30, 40, 50, 60, 70] * (days // 7 + 1), dtype=float)[:days]


def _noisy_flat(days, seed=7):
    rng = np.random.default_rng(seed)
    return np.clip(rng.normal(100, 30, days), 5, None)


def test_rolling_splits_never_train_on_the_future():
    splits = list(fc.rolling_origin_splits(n=120, min_train=56, horizon=14, step=7))
    assert splits
    for train_end, test_end in splits:
        train_positions, test_positions = range(0, train_end), range(train_end, test_end)
        assert max(train_positions) < min(test_positions)
        assert train_end >= 56 and test_end - train_end == 14 and test_end <= 120
    origins = [s[0] for s in splits]
    assert origins == sorted(origins) and len(set(origins)) == len(origins)


def test_features_for_a_day_use_only_earlier_days():
    values = _noisy_flat(60)
    dates = pd.date_range("2025-01-01", periods=60, freq="D")
    t = 40
    changed = values.copy()
    changed[t:] = 9999.0  # rewrite the present and future
    assert fc.make_features(values, dates, t) == fc.make_features(changed, dates, t)


def test_daily_series_fills_missing_days_with_zero_and_spans_to_the_last_transaction():
    df = pd.DataFrame(
        {
            "date": pd.to_datetime(["2025-01-01", "2025-01-01", "2025-01-04", "2025-01-06"]),
            "amount": [10.0, 5.0, 20.0, -500.0],  # the last row is income: it extends the window but adds no spend
        }
    )
    series = fc.build_daily_series(df)
    assert list(series.index.strftime("%Y-%m-%d")) == [f"2025-01-0{d}" for d in range(1, 7)]
    assert list(series.values) == [15.0, 0.0, 0.0, 20.0, 0.0, 0.0]


@pytest.mark.parametrize("days", [1, 30, 89])
def test_too_little_history_is_skipped_with_a_readable_reason(days):
    result = fc.run_forecast(_transactions(np.full(days, 50.0)))
    assert result["status"] == "skipped"
    assert str(days) in result["reason"] and "90" in result["reason"]
    assert result["history_days"] == days and result["min_history_days"] == 90
    assert "forecast" not in result and "method" not in result


def test_no_expenses_at_all_is_skipped_not_an_error():
    income_only = pd.DataFrame({"date": pd.to_datetime(["2025-01-01"]), "amount": [-100.0]})
    assert fc.run_forecast(income_only)["status"] == "skipped"


def test_sufficient_history_always_reports_the_baseline_and_model_scores():
    result = fc.run_forecast(_transactions(_noisy_flat(110)))
    assert result["status"] == "completed"
    backtest = result["backtest"]
    assert backtest["baseline"]["mae"] > 0 and backtest["baseline"]["rmse"] > 0
    assert backtest["model"]["mae"] > 0 and backtest["folds"] >= 1
    assert backtest["selected"] in (backtest["baseline"], backtest["model"])
    assert result["history_days"] == 110 and result["interval"] is None
    assert "not financial advice" in result["disclaimer"].lower()


def test_forecast_covers_the_requested_days_starting_the_day_after_the_data_and_is_never_negative():
    result = fc.run_forecast(_transactions(_noisy_flat(110), start="2025-01-01"))
    daily = result["forecast"]["daily"]
    assert len(daily) == PREDICTION_DAYS
    assert daily[0]["date"] == "2025-04-21"  # 110 days from 2025-01-01 ends 2025-04-20
    assert all(point["predicted_spending"] >= 0 for point in daily)
    assert result["forecast"]["total"] == pytest.approx(sum(p["predicted_spending"] for p in daily), rel=1e-3)


def test_the_baseline_is_kept_when_the_model_is_not_better():
    # A perfectly repeating weekly pattern is predicted exactly by "same weekday last week".
    result = fc.run_forecast(_transactions(_weekly_pattern(120)))
    assert result["backtest"]["baseline"]["mae"] == pytest.approx(0.0, abs=1e-9)
    assert result["method"] == fc.METHOD_BASELINE and result["model_beat_baseline"] is False
    assert result["backtest"]["selected"] == result["backtest"]["baseline"]


def test_the_model_is_selected_only_when_it_beats_the_baseline():
    result = fc.run_forecast(_transactions(_noisy_flat(150)))
    backtest = result["backtest"]
    assert backtest["model"]["mae"] < backtest["baseline"]["mae"]
    assert result["method"] == fc.METHOD_MODEL
    assert backtest["model_vs_baseline_mae_improvement_pct"] > 0


def test_choose_method_is_strict():
    assert fc.choose_method(baseline_mae=10.0, model_mae=9.99) == fc.METHOD_MODEL
    assert fc.choose_method(baseline_mae=10.0, model_mae=10.0) == fc.METHOD_BASELINE
    assert fc.choose_method(baseline_mae=10.0, model_mae=12.0) == fc.METHOD_BASELINE


def test_forecasting_is_deterministic():
    df = _transactions(_noisy_flat(110))
    assert fc.run_forecast(df)["forecast"] == fc.run_forecast(df)["forecast"]


def test_baseline_repeats_the_last_week():
    values = np.arange(1.0, 15.0)
    np.testing.assert_array_equal(fc.forecast_baseline(values, 9), np.array([8, 9, 10, 11, 12, 13, 14, 8, 9], dtype=float))


@pytest.mark.parametrize(
    "history_days,expected_horizon",
    [(90, 14), (99, 14), (100, 21), (112, 21), (120, 31), (361, 31)],
)
def test_backtest_uses_the_longest_horizon_that_still_gives_enough_folds(history_days, expected_horizon):
    assert fc.pick_horizon(history_days) == expected_horizon
    folds = list(fc.rolling_origin_splits(history_days, fc.MIN_TRAIN_DAYS, expected_horizon, fc.BACKTEST_STEP_DAYS))
    assert len(folds) >= fc.MIN_FOLDS


def test_a_longer_history_is_scored_at_the_horizon_we_serve():
    short = fc.run_forecast(_transactions(_noisy_flat(90)))["backtest"]
    long = fc.run_forecast(_transactions(_noisy_flat(150)))["backtest"]
    assert short["horizon_days"] == 14 and short["folds"] >= fc.MIN_FOLDS
    assert long["horizon_days"] == PREDICTION_DAYS == 31
    assert long["forecast_days_scored"] == long["folds"] * 31


def test_backtest_reports_the_error_on_window_totals_for_both_methods():
    backtest = fc.run_forecast(_transactions(_noisy_flat(150)))["backtest"]
    for key in ("baseline", "model"):
        assert backtest[key]["window_total_error_pct"] >= 0 and backtest[key]["mae"] > 0


def test_window_total_error_is_zero_for_a_perfect_forecast_and_correct_for_a_known_miss():
    windows = [np.array([10.0, 10.0]), np.array([20.0, 20.0])]
    assert fc._window_total_error_pct(windows, windows) == 0.0
    off_by_ten_percent = [w * 1.1 for w in windows]
    assert fc._window_total_error_pct(windows, off_by_ten_percent) == pytest.approx(10.0)
