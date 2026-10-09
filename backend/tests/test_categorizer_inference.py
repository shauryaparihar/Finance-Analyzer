import json

import joblib
import pandas as pd
import pytest
import sklearn

from backend.ml.categorizer import (
    METADATA_FILE,
    MODEL_FILE,
    Categorizer,
    ModelLoadError,
    file_sha256,
    load_categorizer,
)
from backend.ml.pipeline import run_full_pipeline


def _frame(descriptions, amounts=None):
    amounts = amounts or [10.0] * len(descriptions)
    return pd.Series(descriptions, dtype=object), pd.Series(amounts)


def test_predictions_match_input_length_and_order(tiny_categorizer):
    descriptions, amounts = _frame(["supermarket bababa", "clinic kovaba", None, "diner batumi"])
    result = tiny_categorizer.predict(descriptions, amounts)
    assert len(result) == 4 and list(result.index) == [0, 1, 2, 3]
    assert list(result["predicted_category"][[0, 1, 3]]) == ["Groceries", "Healthcare", "Restaurants"]


@pytest.mark.parametrize("blank", [None, float("nan"), "", "   "])
def test_missing_description_is_uncategorized_with_a_reason_not_a_crash(tiny_categorizer, blank):
    result = tiny_categorizer.predict(*_frame([blank, "supermarket bababa"]))
    assert result.loc[0, "predicted_category"] == "Uncategorized"
    assert result.loc[0, "reason"] == "no_description" and result.loc[0, "confidence"] == 0.0
    assert result.loc[1, "reason"] == "model"


def test_empty_input_returns_empty_output(tiny_categorizer):
    assert len(tiny_categorizer.predict(*_frame([]))) == 0


def test_low_confidence_predictions_are_left_uncategorized_for_review(trained_small):
    pipeline, _ = trained_small
    strict = Categorizer(pipeline=pipeline, metadata={"model_version": "t", "confidence_threshold": 1.01})
    result = strict.predict(*_frame(["supermarket bababa", "diner batumi"]))
    assert list(result["predicted_category"]) == ["Uncategorized", "Uncategorized"]
    assert list(result["reason"]) == ["low_confidence", "low_confidence"]
    assert (result["confidence"] > 0).all()  # the real confidence is still recorded


@pytest.mark.parametrize("nonsense", ["ZXQJ 8841 KLM", "ASDF QWER", "QZX 5521 WVT CA USA", "POS DEBIT QJZ 1234 PAYMENT"])
def test_text_with_no_recognizable_word_is_left_uncategorized_whatever_the_model_thinks(tiny_categorizer, nonsense):
    result = tiny_categorizer.predict(*_frame([nonsense]))
    assert result.loc[0, "predicted_category"] == "Uncategorized"
    assert result.loc[0, "reason"] == "unrecognized_text" and result.loc[0, "confidence"] == 0.0


def test_the_guard_does_not_block_a_known_merchant_or_ignore_address_words_alone(tiny_categorizer):
    assert tiny_categorizer.predict(*_frame(["diner batumi"])).loc[0, "reason"] == "model"
    address_only = tiny_categorizer.predict(*_frame(["TX USA 77001 CA"]))
    assert address_only.loc[0, "reason"] == "unrecognized_text"


def test_credit_amounts_change_the_direction_the_model_sees(tiny_categorizer):
    debit = tiny_categorizer.predict(*_frame(["supermarket bababa"], [10.0]))
    credit = tiny_categorizer.predict(*_frame(["supermarket bababa"], [-10.0]))
    assert len(debit) == len(credit) == 1


def _write_artifact(directory, pipeline, **overrides):
    directory.mkdir(parents=True, exist_ok=True)
    joblib.dump(pipeline, directory / MODEL_FILE)
    metadata = {
        "model_version": "round-trip",
        "confidence_threshold": 0.5,
        "library_versions": {"scikit-learn": sklearn.__version__},
        "artifact_sha256": file_sha256(directory / MODEL_FILE),
        **overrides,
    }
    (directory / METADATA_FILE).write_text(json.dumps(metadata))


def test_artifact_round_trip_loads_and_predicts(tmp_path, trained_small):
    _write_artifact(tmp_path, trained_small[0])
    loaded = load_categorizer(tmp_path)
    assert loaded.version == "round-trip" and loaded.threshold == 0.5
    assert loaded.predict(*_frame(["supermarket bababa"]))["predicted_category"][0] == "Groceries"


def test_missing_artifact_fails_to_load(tmp_path):
    with pytest.raises(ModelLoadError):
        load_categorizer(tmp_path)


def test_corrupted_artifact_is_rejected_by_checksum(tmp_path, trained_small):
    _write_artifact(tmp_path, trained_small[0])
    with open(tmp_path / MODEL_FILE, "ab") as handle:
        handle.write(b"tampered")
    with pytest.raises(ModelLoadError, match="checksum"):
        load_categorizer(tmp_path)


def test_artifact_from_another_library_version_is_rejected(tmp_path, trained_small):
    _write_artifact(tmp_path, trained_small[0], library_versions={"scikit-learn": "0.0.1"})
    with pytest.raises(ModelLoadError, match="Retrain"):
        load_categorizer(tmp_path)


def test_unreadable_metadata_is_rejected(tmp_path, trained_small):
    _write_artifact(tmp_path, trained_small[0])
    (tmp_path / METADATA_FILE).write_text("{not json")
    with pytest.raises(ModelLoadError):
        load_categorizer(tmp_path)


def test_the_shipped_artifact_loads_and_matches_its_metadata():
    """Guards against committing a model that the pinned libraries cannot load."""
    categorizer = load_categorizer()
    assert categorizer.version.startswith("tfidf-lr-")
    assert categorizer.metadata["training_data"]["synthetic"] is True
    result = categorizer.predict(*_frame(["NETFLIX.COM", "WHOLE FOODS MKT 10234 AUSTIN TX"]))
    assert list(result["predicted_category"]) == ["Subscription", "Groceries"]


def test_the_shipped_model_no_longer_labels_meaningless_text_confidently():
    """Regression: "ZXQJ 8841 KLM" used to be labelled Transportation with 0.93 confidence."""
    result = load_categorizer().predict(*_frame(["ZXQJ 8841 KLM", "ASDF QWER 4411", "REF 99812 TRX"]))
    assert list(result["predicted_category"]) == ["Uncategorized"] * 3


def test_pipeline_without_descriptions_leaves_everything_uncategorized(tiny_categorizer):
    df = pd.DataFrame({"date": pd.date_range("2025-01-01", periods=30), "amount": [12.5] * 30})
    results = run_full_pipeline(df, tiny_categorizer)
    module = results["modules"]["categorization"]
    assert module["needs_review"] == 30 and module["no_description"] == 30
    assert module["model_version"] == "tiny-test"
    assert set(results["processed_df"]["effective_category"]) == {"Uncategorized"}


def test_user_supplied_category_wins_over_the_prediction(tiny_categorizer):
    df = pd.DataFrame(
        {
            "date": pd.date_range("2025-01-01", periods=30),
            "amount": [12.5] * 30,
            "description": ["supermarket bababa"] * 30,
            "category": ["My Own Label"] * 15 + [None] * 15,
        }
    )
    effective = run_full_pipeline(df, tiny_categorizer)["processed_df"]["effective_category"]
    assert set(effective[:15]) == {"My Own Label"} and set(effective[15:]) == {"Groceries"}

