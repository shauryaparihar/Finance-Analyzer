"""
Application configuration.
"""
import os
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Base directory
BASE_DIR = Path(__file__).resolve().parent.parent.parent


class Settings(BaseSettings):
    """Environment-driven settings. Real values come from env vars or a local .env file."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: str = "development"
    database_url: str = "postgresql+psycopg://finsight:finsight@localhost:5432/finsight"
    frontend_url: str = "http://localhost:5173"

    @field_validator("database_url", mode="before")
    @classmethod
    def _normalize_database_url(cls, value: str) -> str:
        # An empty env var (common on hosting dashboards) should fall back to the default.
        if not value:
            return cls.model_fields["database_url"].default
        # Hosts such as Render hand out "postgres://" or "postgresql://" URLs; we use psycopg 3 explicitly.
        for prefix in ("postgres://", "postgresql://"):
            if value.startswith(prefix):
                return "postgresql+psycopg://" + value[len(prefix):]
        return value

    @field_validator("database_url")
    @classmethod
    def _require_postgres(cls, value: str) -> str:
        if not value.startswith("postgresql+psycopg://"):
            raise ValueError("DATABASE_URL must be a PostgreSQL URL starting with postgresql+psycopg://")
        return value


settings = Settings()

# Database (PostgreSQL only; schema is owned by Alembic migrations)
DATABASE_URL = settings.database_url

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
FRONTEND_URL = settings.frontend_url

# Categories
DEFAULT_CATEGORIES = [
    "Groceries", "Rent", "Utilities", "Entertainment", "Dining",
    "Transportation", "Healthcare", "Shopping", "Subscriptions", "Salary"
]

