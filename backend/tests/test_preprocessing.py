import pandas as pd
import pytest

from backend.ml.preprocessing import preprocess_full


def test_preprocess_happy_path(raw_transactions):
    df = preprocess_full(raw_transactions)
    assert len(df) == 3
    assert pd.api.types.is_datetime64_any_dtype(df["date"])
    assert {"weekday", "month", "abs_amount"}.issubset(df.columns)
    # Missing text is left missing (not invented) so the categorizer can report "no description" honestly.
    assert pd.isna(df["description"].iloc[2])
    assert pd.isna(df["category"].iloc[2])


def test_preprocess_drops_bad_rows():
    raw = pd.DataFrame(
        {
            "date": ["2025-01-01", "not-a-date", "2025-01-03"],
            "amount": [10.0, 5.0, None],
        }
    )
    df = preprocess_full(raw)
    assert len(df) == 1
    assert df["amount"].iloc[0] == 10.0


def test_preprocess_requires_amount_column():
    with pytest.raises(KeyError):
        preprocess_full(pd.DataFrame({"date": ["2025-01-01"]}))
