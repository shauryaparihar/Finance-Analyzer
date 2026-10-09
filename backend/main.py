"""
FastAPI application entry point.
"""
import os

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from backend.api.routes import router
from backend.core.config import FRONTEND_URL
from backend.core.database import engine

app = FastAPI(
    title="Personal Finance Analyzer & Expense Predictor",
    description="ML-powered financial analysis API",
    version="1.0.0",
)

# CORS — allow the deployed frontend + localhost for dev
allowed_origins = [
    FRONTEND_URL,
    "http://localhost:5173",
    "http://localhost:3000",
]
# In development, also allow all origins
if os.getenv("ENVIRONMENT", "development") == "development":
    allowed_origins = ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API routes
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
    """Readiness: the database answers. (The model artifact check is added with the categorizer.)"""
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception:
        raise HTTPException(status_code=503, detail="Database unavailable")
    return {"status": "ready"}
