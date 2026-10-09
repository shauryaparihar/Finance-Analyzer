import itertools
import os
from types import SimpleNamespace

import pandas as pd
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL", "postgresql+psycopg://finsight:finsight@localhost:5432/finsight_test"
)


def _alembic_config(url: str) -> Config:
    config = Config("alembic.ini")
    config.attributes["database_url"] = url
    return config


@pytest.fixture(scope="session")
def test_engine():
    """A PostgreSQL engine for a dedicated test database, migrated from empty with Alembic."""
    url = make_url(TEST_DATABASE_URL)
    # Safety: tests drop and recreate tables, so they must never point at a real database.
    assert url.database and url.database.endswith("_test"), "TEST_DATABASE_URL must name a database ending in _test"

    admin = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        exists = conn.scalar(text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": url.database})
        if not exists:
            conn.execute(text(f'CREATE DATABASE "{url.database}"'))
    admin.dispose()

    engine = create_engine(url)
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
    command.upgrade(_alembic_config(url.render_as_string(hide_password=False)), "head")
    yield engine
    engine.dispose()


@pytest.fixture
def db(test_engine):
    """A session on the test database; all rows are removed after each test."""
    session = sessionmaker(bind=test_engine)()
    try:
        yield session
    finally:
        session.rollback()
        session.close()
        with test_engine.begin() as conn:
            conn.execute(text("TRUNCATE users, uploads, upload_inputs, transactions, analysis_runs, analysis_results, budgets CASCADE"))


@pytest.fixture
def raw_transactions() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": ["2025-01-01", "2025-01-02", "2025-01-03"],
            "amount": [10.5, 20.0, 5.25],
            "category": ["Dining", "Groceries", None],
            "description": ["Pizza place", "Supermarket", None],
        }
    )


# --- API fixtures ---

@pytest.fixture
def client(test_engine, db, monkeypatch):
    """A TestClient wired to the test database, with a fast fake analysis pipeline.

    Starlette's TestClient runs background tasks before returning, so analysis is deterministic here.
    """
    from fastapi.testclient import TestClient

    import backend.main as main
    from backend.core.database import get_db
    from backend.main import app
    from backend.ml.pipeline import ModuleOutcome
    from backend.services import analysis_job
    from backend.services.jobs import InlineJobRunner

    factory = sessionmaker(bind=test_engine)

    def override_get_db():
        session = factory()
        try:
            yield session
        finally:
            session.close()

    def fake_pipeline(df, categorizer, observer=None):
        for module in ("categorization", "forecast", "anomaly", "summary"):
            if observer:
                observer.on_start(module)
                observer.on_finish(module, ModuleOutcome("completed", model_version="fake"), 1)
        return {
            "status": "completed",
            "modules": {
                "categorization": {"model_version": categorizer.version, "auto_categorized": 1, "needs_review": 0, "rows": len(df)},
                "summary": {"total_transactions": len(df), "total_spending": float(df["amount"].clip(lower=0).sum())},
                "forecast": {"status": "skipped"},
                "anomaly": {"anomalies": []},
            },
            "errors": [],
            "processed_df": df,
        }

    monkeypatch.setattr(main.app.state, "categorizer", SimpleNamespace(version="test-model", threshold=0.5), raising=False)
    runner = InlineJobRunner(
        factory,
        analysis_job.make_processor(lambda: main.app.state.categorizer),
        is_ready=lambda: main.app.state.categorizer is not None,
        instance_id="test",
        heartbeat_seconds=60,
    )
    monkeypatch.setattr(main.app.state, "job_runner", runner, raising=False)
    monkeypatch.setattr(analysis_job, "run_full_pipeline", fake_pipeline)
    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


PASSWORD = "correct-horse-battery"


def register_and_login(client, email="user@example.com", password=PASSWORD) -> dict:
    """Create an account and return Authorization headers for it."""
    assert client.post("/api/auth/register", json={"email": email, "password": password}).status_code == 201
    token = client.post("/api/auth/login", json={"email": email, "password": password}).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


CSV_OK = (
    "date,amount,description\n"
    "2025-01-01,12.50,Coffee shop\n"
    "2025-01-02,40.00,Grocery store\n"
    "2025-01-03,-2000.00,Salary\n"
).encode()


def csv_file(content: bytes = CSV_OK, name: str = "data.csv"):
    return {"file": (name, content, "text/csv")}


# --- categorizer fixtures ---

def make_training_frame(categories: int = 6, merchants_per_category: int = 30, stores: int = 6) -> pd.DataFrame:
    """A small, learnable dataset: each category has its own words, each merchant has a unique name."""
    category_words = {
        "Groceries": "supermarket fresh produce",
        "Restaurants": "diner grill kitchen",
        "Transportation": "fuel station parking",
        "Utilities": "electric water power",
        "Healthcare": "clinic pharmacy dental",
        "Education": "tuition college course",
    }
    syllables = ["ba", "ko", "ri", "tu", "ne", "so", "mi", "va"]
    names = ("".join(p) for p in itertools.product(syllables, repeat=3))
    rows = []
    for category, words in list(category_words.items())[:categories]:
        for _ in range(merchants_per_category):
            merchant = next(names)
            for store in range(stores):
                rows.append({"description": f"[debit] {words.split()[store % 3]} {merchant} #{1000 + store}", "category": category})
    return pd.DataFrame(rows)


@pytest.fixture(scope="session")
def trained_small():
    """(pipeline, results) from the real training code on the small dataset."""
    from backend.ml.train_categorizer import train_and_evaluate

    return train_and_evaluate(make_training_frame())


@pytest.fixture
def tiny_categorizer(trained_small):
    from backend.ml.categorizer import Categorizer

    pipeline, results = trained_small
    return Categorizer(pipeline=pipeline, metadata={"model_version": "tiny-test", "confidence_threshold": 0.5})
