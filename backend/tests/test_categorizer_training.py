import json

import numpy as np
import pytest

from backend.ml.rules import classify_with_rules
from backend.ml.text import direction_from_amount, merchant_group, normalize_description
from backend.ml.train_categorizer import (
    CANDIDATE_THRESHOLDS,
    prepare_frame,
    split_by_group,
    train_and_evaluate,
)
from backend.tests.conftest import make_training_frame


def test_group_split_never_shares_a_merchant_between_test_and_development():
    df = prepare_frame(make_training_frame())
    splits = split_by_group(df)
    test_groups = set(df.iloc[splits["test"]]["group"])
    dev_groups = set(df.iloc[splits["development"]]["group"])
    assert test_groups and dev_groups and not (test_groups & dev_groups)


def test_group_split_keeps_cross_validation_folds_disjoint_by_group_and_row():
    df = prepare_frame(make_training_frame())
    folds = split_by_group(df)["cv_folds"]
    seen_groups, seen_rows = set(), set()
    for fold in folds:
        groups = set(df.iloc[fold]["group"])
        assert not (groups & seen_groups)
        assert not (set(fold) & seen_rows)
        seen_groups |= groups
        seen_rows |= set(fold)


def test_every_row_lands_in_exactly_one_part():
    df = prepare_frame(make_training_frame())
    splits = split_by_group(df)
    combined = np.concatenate([splits["test"], splits["development"]])
    assert sorted(combined) == list(range(len(df)))


def test_training_is_reproducible_with_a_fixed_seed(trained_small):
    _, first = trained_small
    pipeline_again, second = train_and_evaluate(make_training_frame())
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)
    sample = ["dir_debit supermarket zzz", "dir_debit clinic zzz"]
    assert list(trained_small[0].predict(sample)) == list(pipeline_again.predict(sample))


def test_results_report_the_honest_metrics(trained_small):
    _, results = trained_small
    assert results["split"]["group_overlap_development_test"] == 0
    test = results["model_test"]
    assert {"macro_f1", "weighted_f1", "per_class", "confusion_matrix", "accuracy_secondary"} <= set(test)
    assert 0 <= results["model_test_at_threshold"]["coverage_auto_categorized"] <= 1
    assert results["confidence_threshold"] in CANDIDATE_THRESHOLDS
    assert results["cross_validation"]["folds"] == 6
    assert results["rules_baseline_test"]["coverage"] < 1  # the keyword rules cannot handle unknown merchants


def test_text_normalization_removes_numbers_and_adds_direction():
    assert normalize_description("[debit] PUBLIX 7860 UNIVERSITY LN OAKLAND 94601-4574CA USA") == (
        "dir_debit publix university ln oakland ca usa"
    )
    assert normalize_description("ACME PAYROLL PPD ID: 575065659", "credit") == "dir_credit acme payroll ppd"
    assert normalize_description("", None) == "dir_unknown"


def test_direction_follows_the_canonical_amount_sign():
    assert direction_from_amount(10.0) == "debit"
    assert direction_from_amount(-10.0) == "credit"


def test_merchant_group_ignores_store_numbers_and_payment_prefixes():
    assert merchant_group("[debit] WAL-MART #0006") == merchant_group("[debit] WAL-MART #8814")
    assert merchant_group("[debit] SQ *GREEN MARKET CAFE #403") == "green market cafe"
    assert merchant_group("[debit] PUBLIX 7860 UNIVERSITY LN") == "publix"
    assert merchant_group("") == "unknown"


def test_rules_baseline_is_transparent_and_abstains_on_unknowns():
    assert classify_with_rules(normalize_description("NETFLIX.COM")) == "Subscription"
    assert classify_with_rules(normalize_description("ACME PAYROLL", "credit")) == "Income"
    assert classify_with_rules(normalize_description("ZXQJ KLM")) == "Uncategorized"


def test_threshold_choice_prefers_lowest_threshold_meeting_the_target():
    from backend.ml.train_categorizer import choose_threshold

    confidence = np.array([0.95] * 50 + [0.5] * 50)
    correct = np.array([True] * 50 + [False] * 50)
    assert choose_threshold(confidence, correct) == 0.55  # accepting the 0.5 rows would drop accuracy to 50%
    assert choose_threshold(np.full(10, 0.9), np.ones(10, dtype=bool)) == CANDIDATE_THRESHOLDS[0]


@pytest.mark.parametrize("description", [None, float("nan"), "", "   "])
def test_blank_descriptions_in_training_data_are_dropped(description):
    df = make_training_frame().head(10)
    df.loc[0, "description"] = description
    assert len(prepare_frame(df)) == 9
