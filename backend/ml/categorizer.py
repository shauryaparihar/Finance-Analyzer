"""
Transaction categorizer: loading a trusted, versioned artifact and predicting with it.
Training lives in backend/ml/train_categorizer.py and never runs during an upload.
"""
import hashlib
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
import sklearn

from backend.core.config import ARTIFACT_DIR
from backend.ml.text import direction_from_amount, is_blank, normalize_description

logger = logging.getLogger("finsight.ml")

UNCATEGORIZED = "Uncategorized"
MODEL_FILE = "model.joblib"
METADATA_FILE = "metadata.json"


# A description is only trusted if it contains at least one "informative" word: known to the model, rare enough
# to identify something (appears in fewer than about 5% of training descriptions, i.e. IDF >= 4.0), and not an
# address word. Without this, meaningless text such as "ZXQJ 8841 KLM" got confident predictions, because
# logistic regression stays confident on text it has never seen.
MIN_INFORMATIVE_IDF = 4.0
ADDRESS_WORDS = frozenset(
    "al ak az ar ca co ct de fl ga hi id il in ia ks ky la me md ma mi mn ms mo mt ne nv nh nj nm ny nc nd oh ok "
    "or pa ri sc sd tn tx ut vt va wa wv wi wy dc us usa".split()
)


class ModelLoadError(Exception):
    """The categorizer artifact is missing, altered, or built for a different library version."""


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def informative_words(pipeline: Any) -> frozenset:
    """Single words from the model's vocabulary that can identify a merchant or category."""
    vectorizer = pipeline.named_steps["features"].transformer_list[0][1]
    return frozenset(
        word
        for word, index in vectorizer.vocabulary_.items()
        if " " not in word and vectorizer.idf_[index] >= MIN_INFORMATIVE_IDF and word not in ADDRESS_WORDS
    )


def has_informative_word(normalized_text: str, words: frozenset) -> bool:
    return any(token in words for token in normalized_text.split() if not token.startswith("dir_"))


@dataclass
class Categorizer:
    pipeline: Any
    metadata: dict

    def __post_init__(self):
        self._informative = informative_words(self.pipeline)

    @property
    def version(self) -> str:
        return self.metadata["model_version"]

    @property
    def categories(self) -> list[str]:
        """The categories the model can assign (the product's category list)."""
        return sorted(str(c) for c in self.metadata.get("training_data", {}).get("classes", []))

    @property
    def threshold(self) -> float:
        return float(self.metadata["confidence_threshold"])

    def predict(self, descriptions: pd.Series, amounts: pd.Series) -> pd.DataFrame:
        """Return predicted_category, confidence and reason for every row, in the same order as the input."""
        n = len(descriptions)
        result = pd.DataFrame(
            {"predicted_category": [UNCATEGORIZED] * n, "confidence": [0.0] * n, "reason": ["no_description"] * n},
            index=descriptions.index,
        )
        if n == 0:
            return result

        has_text = np.array([not is_blank(d) for d in descriptions])
        if has_text.any():
            texts = [
                normalize_description(str(d), direction_from_amount(float(a)))
                for d, a, ok in zip(descriptions, amounts, has_text)
                if ok
            ]
            probabilities = self.pipeline.predict_proba(texts)
            best = probabilities.argmax(axis=1)
            confidence = probabilities.max(axis=1)
            labels = self.pipeline.classes_[best]
            recognized = np.array([has_informative_word(t, self._informative) for t in texts])
            confident = (confidence >= self.threshold) & recognized

            positions = np.flatnonzero(has_text)
            reason = np.where(~recognized, "unrecognized_text", np.where(confident, "model", "low_confidence"))
            result.iloc[positions, result.columns.get_loc("confidence")] = np.where(recognized, confidence, 0.0)
            result.iloc[positions, result.columns.get_loc("predicted_category")] = np.where(confident, labels, UNCATEGORIZED)
            result.iloc[positions, result.columns.get_loc("reason")] = reason
        return result


def load_categorizer(directory: Path = ARTIFACT_DIR) -> Categorizer:
    """Load the artifact that ships with the application. Raises ModelLoadError if anything is off."""
    model_path, metadata_path = directory / MODEL_FILE, directory / METADATA_FILE
    if not model_path.exists() or not metadata_path.exists():
        raise ModelLoadError("Categorizer artifact not found. Run: python -m backend.ml.train_categorizer")
    try:
        metadata = json.loads(metadata_path.read_text())
    except (OSError, ValueError) as e:
        raise ModelLoadError("Categorizer metadata is unreadable") from e

    # Integrity: refuse to deserialize a file that is not the one the training run produced.
    if file_sha256(model_path) != metadata.get("artifact_sha256"):
        raise ModelLoadError("Categorizer artifact does not match its recorded checksum")
    trained_with = metadata.get("library_versions", {}).get("scikit-learn")
    if trained_with != sklearn.__version__:
        raise ModelLoadError(
            f"Categorizer was trained with scikit-learn {trained_with} but {sklearn.__version__} is installed. Retrain."
        )
    try:
        pipeline = joblib.load(model_path)
    except Exception as e:
        raise ModelLoadError("Categorizer artifact could not be loaded") from e
    logger.info("categorizer_loaded version=%s threshold=%s", metadata["model_version"], metadata["confidence_threshold"])
    return Categorizer(pipeline=pipeline, metadata=metadata)
