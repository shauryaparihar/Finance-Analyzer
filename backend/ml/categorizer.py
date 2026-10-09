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


class ModelLoadError(Exception):
    """The categorizer artifact is missing, altered, or built for a different library version."""


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass
class Categorizer:
    pipeline: Any
    metadata: dict

    @property
    def version(self) -> str:
        return self.metadata["model_version"]

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
            confident = confidence >= self.threshold

            positions = np.flatnonzero(has_text)
            result.iloc[positions, result.columns.get_loc("confidence")] = confidence
            result.iloc[positions, result.columns.get_loc("predicted_category")] = np.where(confident, labels, UNCATEGORIZED)
            result.iloc[positions, result.columns.get_loc("reason")] = np.where(confident, "model", "low_confidence")
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
