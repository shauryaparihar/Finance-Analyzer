import pandas as pd
import pytest

from backend.utils.amounts import AmountConventionError, apply_amount_convention


def _frame(amounts):
    return pd.DataFrame({"date": ["2025-01-01"] * len(amounts), "amount": amounts})


def test_auto_keeps_a_file_that_already_uses_expenses_positive():
    df, used = apply_amount_convention(_frame([10, 20, 30, -500]))
    assert used == "expenses_positive"
    assert list(df["amount"]) == [10, 20, 30, -500]


def test_auto_flips_a_file_that_uses_expenses_negative():
    df, used = apply_amount_convention(_frame([-10, -20, -30, 500]))
    assert used == "expenses_negative"
    assert list(df["amount"]) == [10, 20, 30, -500]


def test_auto_treats_all_negative_file_as_expenses_negative():
    _, used = apply_amount_convention(_frame([-1, -2, -3]))
    assert used == "expenses_negative"


def test_auto_refuses_to_guess_when_signs_are_evenly_mixed():
    with pytest.raises(AmountConventionError):
        apply_amount_convention(_frame([10, 20, -10, -20]))


def test_explicit_convention_overrides_detection():
    df, used = apply_amount_convention(_frame([10, 20, -10, -20]), "expenses_negative")
    assert used == "expenses_negative"
    assert list(df["amount"]) == [-10, -20, 10, 20]


def test_unknown_convention_is_rejected():
    with pytest.raises(AmountConventionError):
        apply_amount_convention(_frame([1]), "whatever")


def test_non_numeric_amounts_become_missing_instead_of_crashing():
    df, _ = apply_amount_convention(_frame(["12.5", "abc", "7"]))
    assert df["amount"].isna().sum() == 1
