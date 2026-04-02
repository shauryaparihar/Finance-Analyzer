"""
Data cleaning and feature engineering for ML pipeline.
"""
import pandas as pd
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from typing import Tuple


def clean_data(df: pd.DataFrame) -> pd.DataFrame:
    """Clean the raw DataFrame: handle missing values, remove duplicates."""
    df = df.copy()

    # Remove exact duplicates
    df = df.drop_duplicates()

    # Handle missing amounts — drop rows with no amount
    df = df.dropna(subset=["amount"])

    # Fill missing descriptions
    if "description" in df.columns:
        df["description"] = df["description"].fillna("Unknown transaction")

    # Fill missing categories
    if "category" in df.columns:
        df["category"] = df["category"].fillna("Uncategorized")

    # Remove rows with zero amount
    df = df[df["amount"] != 0]

    df = df.reset_index(drop=True)
    return df


def parse_dates(df: pd.DataFrame) -> pd.DataFrame:
    """Parse date column, handling multiple formats."""
    df = df.copy()

    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"], format="mixed", dayfirst=False, errors="coerce")
        # Drop rows where date couldn't be parsed
        initial_len = len(df)
        df = df.dropna(subset=["date"])
        if len(df) < initial_len:
            print(f"  ⚠ Dropped {initial_len - len(df)} rows with unparseable dates")

    return df.reset_index(drop=True)


def engineer_features(df: pd.DataFrame) -> pd.DataFrame:
    """Extract temporal features from date column."""
    df = df.copy()

    if "date" in df.columns and pd.api.types.is_datetime64_any_dtype(df["date"]):
        df["day"] = df["date"].dt.day
        df["month"] = df["date"].dt.month
        df["year"] = df["date"].dt.year
        df["weekday"] = df["date"].dt.weekday  # 0=Mon, 6=Sun
        df["week_of_year"] = df["date"].dt.isocalendar().week.astype(int)
        df["is_weekend"] = df["weekday"].isin([5, 6]).astype(int)
        df["day_of_month"] = df["date"].dt.day
        df["quarter"] = df["date"].dt.quarter

    # Absolute amount for expenses
    df["abs_amount"] = df["amount"].abs()

    return df


def prepare_for_classification(df: pd.DataFrame) -> Tuple[np.ndarray, np.ndarray, TfidfVectorizer]:
    """
    Prepare features for expense categorization.
    Uses TF-IDF on description + numerical features.
    Returns: (feature_matrix, labels, vectorizer)
    """
    from backend.core.config import MAX_TRAINING_SAMPLES, MAX_TFIDF_FEATURES
    
    # Filter to rows that have categories (for supervised learning)
    labeled_df = df[df["category"].notna() & (df["category"] != "Uncategorized")].copy()

    if len(labeled_df) == 0:
        raise ValueError("No labeled data available for classification")

    # Sample for training if dataset is too large
    if len(labeled_df) > MAX_TRAINING_SAMPLES:
        labeled_df = labeled_df.sample(n=MAX_TRAINING_SAMPLES, random_state=42)

    # TF-IDF on descriptions
    vectorizer = TfidfVectorizer(max_features=MAX_TFIDF_FEATURES, stop_words="english", ngram_range=(1, 2))
    tfidf_matrix = vectorizer.fit_transform(labeled_df["description"].fillna(""))

    # Numerical features
    num_features = []
    for col in ["abs_amount", "weekday", "month", "is_weekend", "day_of_month"]:
        if col in labeled_df.columns:
            num_features.append(labeled_df[col].values.reshape(-1, 1))

    if num_features:
        num_matrix = np.hstack(num_features)
        from scipy.sparse import hstack as sparse_hstack
        feature_matrix = sparse_hstack([tfidf_matrix, num_matrix])
    else:
        feature_matrix = tfidf_matrix

    labels = labeled_df["category"].to_numpy(dtype=str)

    return feature_matrix, labels, vectorizer


def prepare_for_regression(df: pd.DataFrame, freq: str = "D") -> pd.DataFrame:
    """
    Aggregate spending by time period for regression/time series.
    freq: 'D' (daily), 'W' (weekly), 'M' (monthly)
    """
    expenses = df[df["amount"] > 0].copy()

    if len(expenses) == 0 or "date" not in expenses.columns:
        return pd.DataFrame(columns=["date", "total_spending"])

    daily = expenses.groupby(pd.Grouper(key="date", freq=freq))["amount"].sum().reset_index()
    daily.columns = ["date", "total_spending"]
    daily = daily.fillna(0)

    return daily


def preprocess_full(df: pd.DataFrame) -> pd.DataFrame:
    """Run the full preprocessing pipeline."""
    print("  → Cleaning data...")
    df = clean_data(df)
    print(f"    {len(df)} rows after cleaning")

    print("  → Parsing dates...")
    df = parse_dates(df)

    print("  → Engineering features...")
    df = engineer_features(df)

    return df
