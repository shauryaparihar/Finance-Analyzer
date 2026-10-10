"""
FastAPI application entry point.
"""
import logging
import os
import socket
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from backend.api.admin import router as admin_router
from backend.api.auth import router as auth_router
from backend.api.errors import AppError, register_error_handling
from backend.api.google_auth import router as google_router
from backend.api.routes import router
from backend.core.config import cors_origins, settings, validate_runtime_settings
from backend.core.database import SessionLocal, engine
from backend.core.logging import configure_logging, log_event
from backend.ml.categorizer import ModelLoadError, load_categorizer
from backend.services.analysis_job import make_processor
from backend.services.jobs import JobRunner

logger = logging.getLogger("finsight.api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    validate_runtime_settings()  # raises in production if the configuration is unsafe
    # Load the trusted categorizer once. If it cannot be loaded the app still starts, but /readyz fails
    # and uploads are refused: we never fall back to silently guessing.
    try:
        app.state.categorizer = load_categorizer()
    except ModelLoadError as e:
        app.state.categorizer = None
        log_event(logger, logging.ERROR, "categorizer_unavailable", reason=str(e))
    # Start this instance's workers. Jobs are claimed from the shared PostgreSQL queue, so other instances can run
    # alongside, and a job interrupted by a restart or crash is recovered from its stale heartbeat (not failed).
    instance_id = f"{socket.gethostname()}-{os.getpid()}-{uuid.uuid4().hex[:6]}"
    app.state.job_runner = JobRunner(
        SessionLocal,
        make_processor(lambda: app.state.categorizer),
        is_ready=lambda: app.state.categorizer is not None,
        instance_id=instance_id,
        workers=settings.analysis_workers,
        poll_seconds=settings.job_poll_seconds,
        heartbeat_seconds=settings.job_heartbeat_seconds,
        stale_after_seconds=settings.job_stale_after_seconds,
        max_attempts=settings.job_max_attempts,
    )
    app.state.job_runner.start()
    log_event(
        logger, logging.INFO, "app_started",
        instance_id=instance_id, workers=settings.analysis_workers, environment=settings.environment,
    )
    yield
    # Shutdown: stop claiming work and let running jobs finish. Queued jobs stay queued for the next worker.
    app.state.job_runner.shutdown()
    log_event(logger, logging.INFO, "app_stopped", instance_id=instance_id)


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
app.include_router(admin_router)
app.include_router(google_router)
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
    runner = getattr(app.state, "job_runner", None)
    if runner is None or not runner.is_running:
        raise AppError(503, "NOT_READY", "Analysis service unavailable.")
    return {"status": "ready", "model_version": app.state.categorizer.version}
