"""
Amount sign convention.

Canonical convention used everywhere after upload:
    amount > 0  -> expense (money out)
    amount < 0  -> income, refund or other money in

Bank exports disagree about this, so uploads can state their convention, or we detect it:
    "expenses_positive" - the file already follows the canonical convention
    "expenses_negative" - the file uses negative numbers for spending; signs are flipped on ingest
    "auto"              - decide from the data; refuse to guess when the signs are too evenly mixed
"""
import pandas as pd

CONVENTIONS = ("auto", "expenses_positive", "expenses_negative")
# If the less common sign makes up more than this share of rows, we cannot tell which sign is spending.
AMBIGUOUS_MINORITY_SHARE = 0.40


class AmountConventionError(ValueError):
    """The amount sign convention is invalid or cannot be determined."""


def apply_amount_convention(df: pd.DataFrame, convention: str = "auto") -> tuple[pd.DataFrame, str]:
    """Return (dataframe with canonical signs, the convention that was applied)."""
    if convention not in CONVENTIONS:
        raise AmountConventionError(f"amount_convention must be one of {list(CONVENTIONS)}")

    df = df.copy()
    df["amount"] = pd.to_numeric(df["amount"], errors="coerce")

    resolved = convention
    if convention == "auto":
        positives = int((df["amount"] > 0).sum())
        negatives = int((df["amount"] < 0).sum())
        if negatives == 0:
            resolved = "expenses_positive"
        elif positives == 0:
            resolved = "expenses_negative"
        else:
            minority_share = min(positives, negatives) / (positives + negatives)
            if minority_share > AMBIGUOUS_MINORITY_SHARE:
                raise AmountConventionError(
                    "Could not tell whether positive or negative amounts are spending. "
                    "Please set amount_convention to 'expenses_positive' or 'expenses_negative'."
                )
            resolved = "expenses_positive" if positives > negatives else "expenses_negative"

    if resolved == "expenses_negative":
        df["amount"] = -df["amount"]
    return df, resolved
