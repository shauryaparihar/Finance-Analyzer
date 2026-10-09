"""
Validation of an uploaded CSV before any analysis runs. Raises AppError with a safe, specific message.
"""
import io
import re
from dataclasses import dataclass

import pandas as pd

from backend.api.errors import AppError
from backend.utils.amounts import AmountConventionError, apply_amount_convention

REQUIRED_COLUMNS = ("date", "amount")


@dataclass
class IngestResult:
    df: pd.DataFrame
    rows_received: int
    rows_dropped: int
    amount_convention: str


def sanitize_filename(raw: str | None) -> str:
    """Keep only a safe base name: no directories, no odd characters, never empty."""
    name = (raw or "").replace("\\", "/").split("/")[-1].strip()
    name = re.sub(r"[^A-Za-z0-9._ -]", "_", name)[:255]
    return name or "upload.csv"


def validate_and_clean_csv(
    contents: bytes, filename: str, convention: str, max_bytes: int, max_rows: int, max_invalid_share: float
) -> IngestResult:
    if not filename.lower().endswith(".csv"):
        raise AppError(400, "UPLOAD_NOT_CSV", "Only .csv files are supported.")
    if len(contents) > max_bytes:
        raise AppError(
            413, "UPLOAD_TOO_LARGE", f"The file is larger than the {max_bytes // (1024 * 1024)} MB limit."
        )
    if not contents.strip():
        raise AppError(400, "UPLOAD_EMPTY", "The file is empty.")
    if b"\x00" in contents[:4096]:
        raise AppError(400, "UPLOAD_MALFORMED", "The file does not look like a text CSV.")

    try:
        # Read one row past the limit so a huge file is rejected without parsing all of it.
        df = pd.read_csv(io.BytesIO(contents), nrows=max_rows + 1)
    except (pd.errors.ParserError, pd.errors.EmptyDataError, UnicodeDecodeError):
        raise AppError(400, "UPLOAD_MALFORMED", "The file could not be read as a CSV.")

    if len(df) > max_rows:
        raise AppError(413, "UPLOAD_TOO_MANY_ROWS", f"The file has more than {max_rows:,} rows.")

    df.columns = df.columns.astype(str).str.lower().str.strip()
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise AppError(
            400,
            "UPLOAD_SCHEMA_INVALID",
            "The CSV must include date and amount columns.",
            {"missing_columns": missing, "found_columns": list(df.columns)[:20]},
        )

    rows_received = len(df)
    if rows_received == 0:
        raise AppError(400, "UPLOAD_EMPTY", "The file has no data rows.")

    df["amount"] = pd.to_numeric(df["amount"], errors="coerce")
    df["date"] = pd.to_datetime(df["date"], format="mixed", errors="coerce")
    invalid = df["amount"].isna() | df["date"].isna()
    invalid_share = float(invalid.mean())
    if invalid_share > max_invalid_share:
        raise AppError(
            400,
            "UPLOAD_TOO_MANY_INVALID_ROWS",
            f"{invalid_share:.0%} of rows have an invalid date or amount (limit {max_invalid_share:.0%}).",
            {"invalid_rows": int(invalid.sum()), "total_rows": rows_received},
        )

    df = df[~invalid].reset_index(drop=True)
    if df.empty:
        raise AppError(400, "UPLOAD_EMPTY", "No valid rows remain after cleaning.")

    try:
        df, resolved = apply_amount_convention(df, convention)
    except AmountConventionError as e:
        raise AppError(400, "AMOUNT_CONVENTION_INVALID", str(e))

    return IngestResult(df=df, rows_received=rows_received, rows_dropped=int(invalid.sum()), amount_convention=resolved)
