"""
FastAPI application entry point.
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from backend.api.routes import router
from backend.core.database import init_db

app = FastAPI(
    title="Personal Finance Analyzer & Expense Predictor",
    description="ML-powered financial analysis API",
    version="1.0.0",
)

# CORS for Streamlit frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API routes
app.include_router(router)


@app.on_event("startup")
async def startup():
    """Initialize database on startup."""
    init_db()
    print("🚀 Finance Analyzer API is running!")


@app.get("/")
async def root():
    return {
        "message": "Personal Finance Analyzer & Expense Predictor API",
        "docs": "/docs",
        "version": "1.0.0",
    }


@app.get("/health")
async def health():
    return {"status": "healthy"}
