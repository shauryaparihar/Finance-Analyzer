import pandas as pd
import pytest


@pytest.fixture
def raw_transactions() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": ["2025-01-01", "2025-01-02", "2025-01-03"],
            "amount": [10.5, 20.0, 5.25],
            "category": ["Dining", "Groceries", None],
            "description": ["Pizza place", "Supermarket", None],
        }
    )
