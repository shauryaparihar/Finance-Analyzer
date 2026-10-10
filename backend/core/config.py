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
    # More exact origins allowed to call the cookie endpoints (comma-separated), e.g. a custom domain. No wildcards.
    extra_frontend_origins: str = ""

    # Authentication. In production JWT_SECRET must be set to a long random value (see validate_runtime_settings).
    jwt_secret: str = ""
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 15  # short: the long-lived credential is the refresh cookie, not this token
    refresh_token_days: int = 7  # each rotated refresh token lasts this long ...
    refresh_family_max_days: int = 30  # ... but a login session can never be extended past this
    refresh_grace_seconds: int = 10  # a just-rotated token presented again within this window is a race, not theft
    cookie_secure: bool | None = None  # None: Secure cookies in production, plain in local development

    # One-click read-only guest login (POST /api/auth/demo). Off unless a deployment turns it on.
    demo_enabled: bool = False

    # Analysis jobs and logging
    analysis_workers: int = 2  # analyses that may run at once in this process
    job_poll_seconds: float = 1.0  # how often an idle worker looks for queued work
    job_heartbeat_seconds: float = 10.0  # how often a running job proves it is alive
    job_stale_after_seconds: float = 60.0  # a processing job with no heartbeat for this long is considered dead
    job_max_attempts: int = 2  # a job whose worker died is re-queued until it has been tried this many times
    max_active_jobs: int = 10  # queued + running analyses across all users before new uploads are refused
    log_level: str = "INFO"
    # Exception messages can echo user data (a bad value, a SQL fragment), so they are never logged unless someone
    # explicitly turns this on for local debugging. The same default applies in every environment.
    log_exception_messages: bool = False

    # Upload limits
    max_upload_bytes: int = 5 * 1024 * 1024
    max_upload_rows: int = 50_000
    max_invalid_row_share: float = 0.20

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

# Only used outside production so local development works without extra setup. Never accepted in production.
DEV_JWT_SECRET = "dev-only-insecure-secret-do-not-use-in-production"


def is_production(current: Settings) -> bool:
    return current.environment.lower() == "production"


def effective_jwt_secret(current: Settings = settings) -> str:
    return current.jwt_secret or DEV_JWT_SECRET


def validate_runtime_settings(current: Settings = settings) -> None:
    """Refuse to start in production with unsafe configuration."""
    if not is_production(current):
        return
    secret = current.jwt_secret
    if not secret or secret == DEV_JWT_SECRET or len(secret) < 32:
        raise RuntimeError("JWT_SECRET must be set to a random value of at least 32 characters in production")
    if not cookie_secure_enabled(current):
        raise RuntimeError("COOKIE_SECURE must not be disabled in production: the refresh cookie must be Secure")
    for origin in [current.frontend_url, *_extra_origins(current)]:
        if not origin.startswith("https://") or "*" in origin or "localhost" in origin:
            raise RuntimeError("FRONTEND_URL and EXTRA_FRONTEND_ORIGINS must be exact https:// origins in production")


def cookie_secure_enabled(current: Settings = settings) -> bool:
    return is_production(current) if current.cookie_secure is None else current.cookie_secure


def log_exception_messages(current: Settings = settings) -> bool:
    return current.log_exception_messages


def _extra_origins(current: Settings) -> list[str]:
    return [o.strip().rstrip("/") for o in current.extra_frontend_origins.split(",") if o.strip()]


def cors_origins(current: Settings = settings) -> list[str]:
    """Exact allowed browser origins. Production allows only the configured frontend (and any explicit extras)."""
    origins = [current.frontend_url.rstrip("/"), *_extra_origins(current)]
    if not is_production(current):
        origins += ["http://localhost:5173", "http://localhost:3000", "http://127.0.0.1:5173"]
    return sorted(set(origins))

# Database (PostgreSQL only; schema is owned by Alembic migrations)
DATABASE_URL = settings.database_url

# File storage
UPLOAD_DIR = BASE_DIR / "data" / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

SAMPLE_DATA_PATH = BASE_DIR / "data" / "sample_transactions.csv"

# Trusted, versioned model artifacts that ship with the application (never user-supplied files)
ARTIFACT_DIR = BASE_DIR / "backend" / "artifacts" / "categorizer"

# ML Config
RANDOM_STATE = 42
TEST_SIZE = 0.2
REVIEW_CAPACITY = 10  # the most unusual transactions a person is asked to review per upload
MIN_DEVIATION_TO_FLAG = 3.0  # an expense must be at least this many robust deviations above its category's typical amount
PREDICTION_DAYS = 31
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

