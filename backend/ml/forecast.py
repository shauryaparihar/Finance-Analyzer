"""
Spending forecast: a simple baseline first, one modest machine-learning model second.

  * Baseline "seasonal naive": predict that a day looks like the same weekday one week earlier.
  * Model "lag random forest": predict a day from the previous day, the same weekday last week, the
    7-day and 28-day average spending before it, and the weekday.

Both are scored with rolling-origin backtesting (train on the past, forecast the next days, move forward in
time, repeat), never with a random split, because shuffling would let the model peek at the future.
The model is used only if its backtest error is lower than the baseline's; otherwise the baseline is served.
"""
from typing import Any, Iterator

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor

from backend.core.config import PREDICTION_DAYS, RANDOM_STATE

MIN_HISTORY_DAYS = 90
BACKTEST_HORIZON_DAYS = 14  # how far ahead each backtest fold forecasts
BACKTEST_STEP_DAYS = 7  # how far the forecast origin moves between folds
MIN_TRAIN_DAYS = 56  # first backtest fold trains on at least 8 weeks
WARMUP = 28  # the slowest feature (28-day average) needs 28 days of past
RECENT_DAYS_SHOWN = 60

METHOD_BASELINE = "seasonal_naive"
METHOD_MODEL = "lag_random_forest"
METHOD_LABELS = {
    METHOD_BASELINE: "Seasonal naive baseline (same weekday last week)",
    METHOD_MODEL: "Lag-feature random forest",
}
DISCLAIMER = "An estimate based only on your past spending pattern. It is not financial advice."


def build_daily_series(df: pd.DataFrame) -> pd.Series:
    """Total spending per calendar day from the first expense to the last transaction, with empty days as 0."""
    expenses = df[df["amount"] > 0]
    if expenses.empty:
        return pd.Series(dtype=float)
    days = expenses["date"].dt.normalize()
    daily = expenses.groupby(days)["amount"].sum()
    end = max(df["date"].max().normalize(), daily.index.max())
    return daily.reindex(pd.date_range(daily.index.min(), end, freq="D"), fill_value=0.0).astype(float)


def rolling_origin_splits(n: int, min_train: int, horizon: int, step: int) -> Iterator[tuple[int, int]]:
    """Yield (train_end, test_end): train on positions [0, train_end), test on [train_end, test_end)."""
    origin = min_train
    while origin + horizon <= n:
        yield origin, origin + horizon
        origin += step


def make_features(values: np.ndarray, dates: pd.DatetimeIndex, t: int) -> list[float]:
    """Features for day t that use only days before t."""
    return [
        values[t - 1],
        values[t - 7],
        values[t - 7 : t].mean(),
        values[t - WARMUP : t].mean(),
        float(dates[t].weekday()),
    ]


def _training_matrix(values: np.ndarray, dates: pd.DatetimeIndex, end: int) -> tuple[np.ndarray, np.ndarray]:
    rows = range(WARMUP, end)
    X = np.array([make_features(values, dates, t) for t in rows])
    return X, values[WARMUP:end]


def _new_model() -> RandomForestRegressor:
    return RandomForestRegressor(n_estimators=100, max_depth=5, min_samples_leaf=5, random_state=RANDOM_STATE, n_jobs=1)


def forecast_baseline(values: np.ndarray, horizon: int) -> np.ndarray:
    """Each future day copies the day 7 days earlier (earlier forecast days feed later ones)."""
    extended = list(values)
    for _ in range(horizon):
        extended.append(extended[-7])
    return np.array(extended[len(values) :])


def forecast_model(values: np.ndarray, dates: pd.DatetimeIndex, horizon: int) -> np.ndarray:
    """Fit on all of `values`, then forecast day by day, feeding each prediction back in as history."""
    X, y = _training_matrix(values, dates, len(values))
    model = _new_model().fit(X, y)
    extended = list(values)
    future_dates = pd.date_range(dates[-1] + pd.Timedelta(days=1), periods=horizon, freq="D")
    all_dates = dates.append(future_dates)
    for _ in range(horizon):
        arr = np.array(extended)
        t = len(extended)
        extended.append(max(0.0, float(model.predict([make_features(arr, all_dates, t)])[0])))
    return np.array(extended[len(values) :])


def _errors(actual: np.ndarray, predicted: np.ndarray) -> dict[str, float]:
    diff = actual - predicted
    return {"mae": float(np.abs(diff).mean()), "rmse": float(np.sqrt((diff**2).mean()))}


def backtest(values: np.ndarray, dates: pd.DatetimeIndex) -> dict[str, Any]:
    """Score baseline and model over rolling-origin folds. Errors are pooled over every forecast day."""
    actual, base_pred, model_pred = [], [], []
    folds = list(rolling_origin_splits(len(values), MIN_TRAIN_DAYS, BACKTEST_HORIZON_DAYS, BACKTEST_STEP_DAYS))
    for train_end, test_end in folds:
        train_values, train_dates = values[:train_end], dates[:train_end]
        horizon = test_end - train_end
        actual.append(values[train_end:test_end])
        base_pred.append(forecast_baseline(train_values, horizon))
        model_pred.append(forecast_model(train_values, train_dates, horizon))
    actual, base_pred, model_pred = (np.concatenate(a) for a in (actual, base_pred, model_pred))
    return {
        "horizon_days": BACKTEST_HORIZON_DAYS,
        "folds": len(folds),
        "forecast_days_scored": int(len(actual)),
        "baseline": _errors(actual, base_pred),
        "model": _errors(actual, model_pred),
    }


def choose_method(baseline_mae: float, model_mae: float) -> str:
    """Use the machine-learning model only if it is strictly better than the baseline."""
    return METHOD_MODEL if model_mae < baseline_mae else METHOD_BASELINE


def run_forecast(df: pd.DataFrame) -> dict[str, Any]:
    """Forecast spending for the next PREDICTION_DAYS days. Returns status 'skipped' when history is too short."""
    series = build_daily_series(df)
    history_days = int(len(series))
    base = {"min_history_days": MIN_HISTORY_DAYS, "history_days": history_days, "disclaimer": DISCLAIMER}
    if history_days < MIN_HISTORY_DAYS:
        return {
            **base,
            "status": "skipped",
            "reason": (
                f"A forecast needs at least {MIN_HISTORY_DAYS} days of spending history, "
                f"but this file covers {history_days} day{'s' if history_days != 1 else ''}."
            ),
        }

    values, dates = series.to_numpy(), series.index
    scores = backtest(values, dates)
    method = choose_method(scores["baseline"]["mae"], scores["model"]["mae"])
    predicted = (
        forecast_model(values, dates, PREDICTION_DAYS)
        if method == METHOD_MODEL
        else forecast_baseline(values, PREDICTION_DAYS)
    )
    future_dates = pd.date_range(dates[-1] + pd.Timedelta(days=1), periods=PREDICTION_DAYS, freq="D")
    baseline_mae, model_mae = scores["baseline"]["mae"], scores["model"]["mae"]
    improvement = (baseline_mae - model_mae) / baseline_mae * 100 if baseline_mae > 0 else 0.0
    selected = scores["model"] if method == METHOD_MODEL else scores["baseline"]

    return {
        **base,
        "status": "completed",
        "reason": None,
        "first_date": dates[0].strftime("%Y-%m-%d"),
        "last_date": dates[-1].strftime("%Y-%m-%d"),
        "method": method,
        "method_label": METHOD_LABELS[method],
        "model_beat_baseline": method == METHOD_MODEL,
        "backtest": {
            **scores,
            "selected": selected,
            "model_vs_baseline_mae_improvement_pct": float(improvement),  # negative = the model was worse
        },
        "forecast": {
            "days": PREDICTION_DAYS,
            "total": float(predicted.sum()),
            "daily": [
                {"date": d.strftime("%Y-%m-%d"), "predicted_spending": float(round(p, 2))}
                for d, p in zip(future_dates, predicted)
            ],
        },
        "recent_actual": [
            {"date": d.strftime("%Y-%m-%d"), "spending": float(round(v, 2))}
            for d, v in series.iloc[-RECENT_DAYS_SHOWN:].items()
        ],
        "interval": None,  # no prediction interval is offered: none is estimated yet
    }
