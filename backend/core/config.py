"""
Application configuration.
"""
import os
from pathlib import Path

# Base directory
BASE_DIR = Path(__file__).resolve().parent.parent.parent

# Database
DATABASE_URL = f"sqlite:///{BASE_DIR / 'finance_analyzer.db'}"

# File storage
UPLOAD_DIR = BASE_DIR / "data" / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

SAMPLE_DATA_PATH = BASE_DIR / "data" / "sample_transactions.csv"

# Models
MODEL_DIR = BASE_DIR / "backend" / "models"
MODEL_DIR.mkdir(parents=True, exist_ok=True)

# ML Config
RANDOM_STATE = 42
TEST_SIZE = 0.2
ANOMALY_CONTAMINATION = 0.05
MAX_CLUSTERS = 8
MIN_CLUSTERS = 2
PREDICTION_DAYS = 30
MAX_TRAINING_SAMPLES = 10000
MAX_TFIDF_FEATURES = 1000
MAX_WORKERS = 2

# API
API_HOST = os.getenv("API_HOST", "127.0.0.1")
API_PORT = int(os.getenv("API_PORT", "8000"))

# Streamlit
STREAMLIT_PORT = int(os.getenv("STREAMLIT_PORT", "8501"))

# Categories
DEFAULT_CATEGORIES = [
    "Groceries", "Rent", "Utilities", "Entertainment", "Dining",
    "Transportation", "Healthcare", "Shopping", "Subscriptions", "Salary"
]
