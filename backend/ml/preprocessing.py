"""
Data cleaning and feature engineering for ML pipeline.
"""

import pandas as pd


def clean_data(df: pd.DataFrame) -> pd.DataFrame:
    """Clean the raw DataFrame: handle missing values, remove duplicates."""
    df = df.copy()

    # Remove exact duplicates
    df = df.drop_duplicates()

    # Handle missing amounts — drop rows with no amount
    df = df.dropna(subset=["amount"])

    # Missing descriptions/categories stay missing: the categorizer reports "Uncategorized" with a reason
    # instead of guessing from made-up text.

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
