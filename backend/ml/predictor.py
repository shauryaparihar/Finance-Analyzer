"""
Expense prediction using regression and time series models.
"""
import pandas as pd
import numpy as np
import joblib
from sklearn.linear_model import LinearRegression
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_squared_error, r2_score
from typing import Dict, Any

from backend.core.config import MODEL_DIR, RANDOM_STATE, PREDICTION_DAYS


def train_predictor(daily_spending: pd.DataFrame) -> Dict[str, Any]:
    """
    Train spending prediction models on aggregated daily data.
    Returns predictions for the next PREDICTION_DAYS days.
    """
    if len(daily_spending) < 10:
        return {"error": "Not enough data for prediction (need at least 10 data points)"}

    df = daily_spending.copy()
    df = df.sort_values("date").reset_index(drop=True)
    df["day_num"] = np.arange(len(df))

    # Features: day_num, day_of_week, month, day_of_month
    df["dow"] = df["date"].dt.weekday
    df["month"] = df["date"].dt.month
    df["dom"] = df["date"].dt.day

    feature_cols = ["day_num", "dow", "month", "dom"]
    X = df[feature_cols].values
    y = df["total_spending"].values

    # Train/test split (time-based: last 20% for testing)
    split_idx = int(len(df) * 0.8)
    X_train, X_test = X[:split_idx], X[split_idx:]
    y_train, y_test = y[:split_idx], y[split_idx:]

    models = {
        "Linear Regression": LinearRegression(),
        "Random Forest": RandomForestRegressor(
            n_estimators=100, random_state=RANDOM_STATE, n_jobs=-1
        ),
    }

    results = {}
    best_rmse = float("inf")
    best_model_name = None
    best_model = None

    for name, model in models.items():
        model.fit(X_train, y_train)
        preds = model.predict(X_test)
        preds = np.maximum(preds, 0)  # spending can't be negative

        rmse = float(np.sqrt(mean_squared_error(y_test, preds)))
        r2 = float(r2_score(y_test, preds)) if len(y_test) > 1 else 0.0

        results[name] = {
            "rmse": rmse,
            "r2": r2,
            "test_predictions": preds.tolist(),
        }

        if rmse < best_rmse:
            best_rmse = rmse
            best_model_name = name
            best_model = model

    # Try ARIMA
    arima_result = _try_arima(df, y)
    if arima_result:
        results["ARIMA"] = arima_result

    # Generate future predictions using best regression model
    last_date = df["date"].max()
    last_day_num = df["day_num"].max()

    future_dates = pd.date_range(start=last_date + pd.Timedelta(days=1), periods=PREDICTION_DAYS)
    future_features = []
    for i, d in enumerate(future_dates):
        future_features.append([
            last_day_num + i + 1,
            d.weekday(),
            d.month,
            d.day,
        ])
    future_X = np.array(future_features)
    future_preds = np.maximum(best_model.predict(future_X), 0)

    # Save best model
    model_path = MODEL_DIR / "predictor.pkl"
    joblib.dump(best_model, model_path)

    # Actual vs predicted for test set
    test_dates = df["date"].iloc[split_idx:].dt.strftime("%Y-%m-%d").tolist()

    return {
        "best_model": best_model_name,
        "model_comparison": {
            name: {"rmse": r["rmse"], "r2": r["r2"]} for name, r in results.items()
        },
        "future_predictions": [
            {"date": d.strftime("%Y-%m-%d"), "predicted_spending": float(round(p, 2))}
            for d, p in zip(future_dates, future_preds)
        ],
        "test_actual": y_test.tolist(),
        "test_predicted": np.maximum(best_model.predict(X_test), 0).tolist(),
        "test_dates": test_dates,
        "total_predicted_30d": float(round(future_preds.sum(), 2)),
        "avg_predicted_daily": float(round(future_preds.mean(), 2)),
        "model_path": str(model_path),
    }


def _try_arima(df: pd.DataFrame, y: np.ndarray) -> Dict[str, Any] | None:
    """Attempt ARIMA modeling. Returns None on failure."""
    try:
        from statsmodels.tsa.arima.model import ARIMA
        import warnings
        warnings.filterwarnings("ignore")

        # Use last 80% for training ARIMA
        split = int(len(y) * 0.8)
        train_y = y[:split]
        test_y = y[split:]

        if len(train_y) < 30:
            return None

        model = ARIMA(train_y, order=(2, 1, 2))
        fitted = model.fit()

        # Forecast test period
        forecast = fitted.forecast(steps=len(test_y))
        forecast = np.maximum(forecast, 0)

        rmse = float(np.sqrt(mean_squared_error(test_y, forecast)))
        r2 = float(r2_score(test_y, forecast)) if len(test_y) > 1 else 0.0

        return {"rmse": rmse, "r2": r2}
    except Exception:
        return None
