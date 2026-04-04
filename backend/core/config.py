"""
Application configuration.
"""
import os
from pathlib import Path

# Base directory
BASE_DIR = Path(__file__).resolve().parent.parent.parent

# Database — use env var for cloud (e.g. PostgreSQL), fall back to SQLite for local dev
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{BASE_DIR / 'finance_analyzer.db'}")

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

# API — bind to 0.0.0.0 in production so containers can receive traffic
API_HOST = os.getenv("API_HOST", "0.0.0.0")
API_PORT = int(os.getenv("API_PORT", "8000"))

# Frontend URL — used for CORS
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:5173")

# Streamlit
STREAMLIT_PORT = int(os.getenv("STREAMLIT_PORT", "8501"))

# Categories
DEFAULT_CATEGORIES = [
    "Groceries", "Rent", "Utilities", "Entertainment", "Dining",
    "Transportation", "Healthcare", "Shopping", "Subscriptions", "Salary"
]

