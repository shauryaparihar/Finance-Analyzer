import json

import pandas as pd
import pytest

from backend.ml import evaluate_real as ev

ROWS = [
    ("2025-01-02", "12.50", "STARBUCKS #4821 SEATTLE WA", "Restaurants"),
    ("2025-01-03", "82.10", "WHOLE FOODS MKT 10234 AUSTIN TX", "Groceries"),
    ("2025-01-04", "1500.00", "AIMCO RENT PMT PPD ID: 4273027363", "Rent"),
    ("2025-01-05", "33.00", "ZXQJ 8841 KLM", "Shopping"),
    ("2025-01-06", "9.99", "NETFLIX.COM", "Subscription"),
    ("2025-01-07", "20.00", "SECRET MERCHANT NAME", "Skip"),
    ("2025-01-08", "abc", "BROKEN AMOUNT", "Groceries"),
    ("2025-01-09", "5.00", "WEIRD LABEL ROW", "NotACategory"),
]


def _write(tmp_path, rows):
    path = tmp_path / "labelled.csv"
    pd.DataFrame(rows, columns=ev.REQUIRED).to_csv(path, index=False)
    return path


def test_report_has_only_aggregates_and_never_row_content(tmp_path):
    report = ev.evaluate(_write(tmp_path, ROWS), enforce_size=False)
    text = json.dumps(report)
    for private in ("STARBUCKS", "WHOLE FOODS", "AIMCO", "ZXQJ", "NETFLIX", "SECRET MERCHANT", "BROKEN AMOUNT", "2025-01", "82.10"):
        assert private not in text
    assert report["rows_scored"] == 5
    assert (report["rows_skipped_by_owner"], report["rows_dropped_unreadable_amount"], report["rows_dropped_unknown_label"]) == (1, 1, 1)
    assert 0.0 <= report["model"]["accuracy"] <= 1.0 and "macro_f1" in report["rules_baseline"]
    assert report["auto_categorized_share"] + report["sent_to_review_share"] == pytest.approx(1.0)
    assert report["per_class_recall_for_classes_with_5_or_more_rows"] == {}  # no class has 5 rows here


def test_the_gibberish_row_is_not_auto_categorized(tmp_path):
    report = ev.evaluate(_write(tmp_path, [ROWS[3]] * 4), enforce_size=False)
    assert report["blocked_by_unrecognized_text_guard_share"] == 1.0
    assert report["auto_categorized_share"] == 0.0


def test_problems_with_the_file_are_reported_without_row_content(tmp_path):
    with pytest.raises(ev.InputProblem) as too_few:
        ev.evaluate(_write(tmp_path, ROWS))
    assert "150-300" in str(too_few.value) and "STARBUCKS" not in str(too_few.value)
    wrong = tmp_path / "wrong.csv"
    wrong.write_text("a,b\n1,2\n")
    with pytest.raises(ev.InputProblem, match="exactly these columns"):
        ev.evaluate(wrong)
    with pytest.raises(ev.InputProblem, match="does not exist"):
        ev.evaluate(tmp_path / "missing.csv")


def test_the_report_goes_to_the_gitignored_private_folder():
    assert "data/private" in str(ev.DEFAULT_REPORT).replace("\\", "/")
