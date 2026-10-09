import os

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
            conn.execute(text("TRUNCATE users, uploads, transactions, analysis_runs, analysis_results, budgets CASCADE"))


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
