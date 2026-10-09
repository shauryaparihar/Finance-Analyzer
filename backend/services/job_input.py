"""
Encoding of a job's cleaned input for storage in the database while the job waits or runs.

Only the columns the analysis uses are kept (date, amount, description, category): extra columns a user's file
happened to contain are dropped, and the stored copy is deleted when the job finishes.
"""
import gzip
import io

import pandas as pd

KEPT_COLUMNS = ("date", "amount", "description", "category")


def encode_input(df: pd.DataFrame) -> bytes:
    columns = [c for c in KEPT_COLUMNS if c in df.columns]
    out = df[columns].copy()
    out["date"] = pd.to_datetime(out["date"]).dt.strftime("%Y-%m-%dT%H:%M:%S")  # one explicit format, always
    buffer = io.StringIO()
    out.to_csv(buffer, index=False)
    return gzip.compress(buffer.getvalue().encode("utf-8"))


def decode_input(data: bytes) -> pd.DataFrame:
    """Rebuild the DataFrame exactly as the pipeline expects it: parsed dates, float amounts, text as text."""
    text = gzip.decompress(data).decode("utf-8")
    header = text.split("\n", 1)[0].split(",")
    text_columns = {c: str for c in ("description", "category") if c in header}
    df = pd.read_csv(io.StringIO(text), dtype=text_columns, keep_default_na=True, na_values=[""])
    df["date"] = pd.to_datetime(df["date"], format="ISO8601")
    df["amount"] = df["amount"].astype(float)
    return df
