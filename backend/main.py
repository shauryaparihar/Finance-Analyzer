"""
FastAPI application entry point.
"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from backend.api.auth import router as auth_router
from backend.api.errors import AppError, register_error_handling
from backend.api.routes import router
from backend.core import repository as repo
from backend.core.config import cors_origins, validate_runtime_settings
from backend.core.database import SessionLocal, engine
from backend.ml.categorizer import ModelLoadError, load_categorizer

logger = logging.getLogger("finsight.api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    validate_runtime_settings()  # raises in production if the configuration is unsafe
    # Load the trusted categorizer once. If it cannot be loaded the app still starts, but /readyz fails
    # and uploads are refused: we never fall back to silently guessing.
    try:
        app.state.categorizer = load_categorizer()
    except ModelLoadError as e:
        app.state.categorizer = None
        logger.error("categorizer_unavailable reason=%s", e)
    try:
        with SessionLocal() as db:
            stale = repo.fail_stale_uploads(db)
        if stale:
            logger.warning("stale_uploads_marked_failed count=%s", stale)
    except Exception:
        logger.exception("startup_stale_upload_sweep_failed")
    yield


app = FastAPI(
    title="Personal Finance Analyzer & Expense Predictor",
    description="ML-powered financial analysis API",
    version="1.0.0",
    lifespan=lifespan,
)

# Exact browser origins only. Authentication uses a bearer token header, not cookies, so credentials stay off.
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins(),
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
    expose_headers=["X-Request-ID"],
)
register_error_handling(app)

app.include_router(auth_router)
app.include_router(router)


@app.get("/")
async def root():
    return {
        "message": "Personal Finance Analyzer & Expense Predictor API",
        "docs": "/docs",
        "version": "1.0.0",
    }


@app.get("/healthz")
async def healthz():
    """Liveness: the process is up. Deliberately checks nothing else."""
    return {"status": "healthy"}


@app.get("/readyz")
async def readyz():
    """Readiness: the database answers and the categorization model is loaded."""
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception:
        raise AppError(503, "NOT_READY", "Database unavailable.")
    if getattr(app.state, "categorizer", None) is None:
        raise AppError(503, "NOT_READY", "Categorization model unavailable.")
    return {"status": "ready", "model_version": app.state.categorizer.version}
