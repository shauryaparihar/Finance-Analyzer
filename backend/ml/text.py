"""
Text normalization shared by training and inference. Using one implementation for both is what
prevents "train/serve skew" (the model seeing differently-shaped text in production than in training).
"""
import re

import pandas as pd

DIRECTION_DEBIT = "debit"  # money out (canonical amount > 0)
DIRECTION_CREDIT = "credit"  # money in (canonical amount < 0)

_DIRECTION_PREFIX = re.compile(r"^\s*\[(debit|credit)\]\s*", re.IGNORECASE)
_REFERENCE_ID = re.compile(r"\bid:\s*\S+")
_NON_LETTERS = re.compile(r"[^a-z\s]")
_SPACES = re.compile(r"\s+")
_GENERIC_PREFIXES = re.compile(
    r"^(withdrawal from|express checkout payment:?|payment to|purchase at|purchase|pos debit|pos|"
    r"debit card purchase|checkcard|recurring payment|pypl|paypal|sq|tst|sp)\b\s*"
)


def direction_from_amount(amount: float) -> str:
    """Canonical convention: positive amounts are money out (debit), negative are money in (credit)."""
    return DIRECTION_CREDIT if amount < 0 else DIRECTION_DEBIT


def split_direction(raw: str) -> tuple[str | None, str]:
    """Separate an optional leading "[debit]"/"[credit]" marker (present in the training data) from the text."""
    match = _DIRECTION_PREFIX.match(raw)
    if match:
        return match.group(1).lower(), raw[match.end():]
    return None, raw


def normalize_description(raw: str, direction: str | None = None) -> str:
    """Lowercase, drop numbers/codes/punctuation, and prepend a token saying whether money went out or in."""
    prefix_direction, text = split_direction(raw if isinstance(raw, str) else "")
    direction = prefix_direction or direction or "unknown"
    text = _REFERENCE_ID.sub(" ", text.lower())
    text = _SPACES.sub(" ", _NON_LETTERS.sub(" ", text)).strip()
    return f"dir_{direction} {text}".strip()


def merchant_group(raw: str) -> str:
    """A rough merchant key used to keep the same merchant out of both train and test sets.

    Heuristic: remove generic payment-method prefixes, then keep the first words up to the first token
    containing a digit (store numbers and addresses start there). It is not perfect: the same merchant
    written two different ways can land in two groups.
    """
    _, text = split_direction(raw if isinstance(raw, str) else "")
    text = text.lower().replace("*", " ").replace(":", " ")
    for _ in range(2):
        text = _GENERIC_PREFIXES.sub("", text.strip())
    words: list[str] = []
    for token in text.split():
        if any(ch.isdigit() for ch in token) or token.startswith("#"):
            break
        letters = re.sub(r"[^a-z]", "", token)
        if letters:
            words.append(letters)
        if len(words) == 3:
            break
    return " ".join(words) or "unknown"


def is_blank(value) -> bool:
    return value is None or (isinstance(value, float) and pd.isna(value)) or not str(value).strip()
