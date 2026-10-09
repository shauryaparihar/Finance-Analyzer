"""
Download the approved training dataset (pinned to an exact revision) into data/training/.

    python -m backend.ml.prepare_training_data

Source: DoDataThings/us-bank-transaction-categories-v2 on Hugging Face (MIT license, synthetic data).
"""
import hashlib
import urllib.request

from backend.core.config import BASE_DIR

DATASET_URL = (
    "https://huggingface.co/datasets/DoDataThings/us-bank-transaction-categories-v2/resolve/"
    "3e8d052cb7b362fb1a04b6064d2331982553ea56/transactions-synthetic.csv"
)
DATASET_PATH = BASE_DIR / "data" / "training" / "transactions-synthetic.csv"


def sha256_of(path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    DATASET_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not DATASET_PATH.exists():
        print(f"Downloading {DATASET_URL}")
        urllib.request.urlretrieve(DATASET_URL, DATASET_PATH)
    print(f"{DATASET_PATH}  sha256={sha256_of(DATASET_PATH)}")


if __name__ == "__main__":
    main()
