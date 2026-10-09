from alembic import command
from sqlalchemy import inspect

from backend.tests.conftest import TEST_DATABASE_URL, _alembic_config

EXPECTED_TABLES = {"users", "uploads", "transactions", "analysis_runs", "analysis_results", "budgets"}


def test_migration_creates_all_tables(test_engine):
    assert EXPECTED_TABLES.issubset(set(inspect(test_engine).get_table_names()))


def test_key_indexes_and_constraints_exist(test_engine):
    inspector = inspect(test_engine)
    assert "ix_uploads_user_id_content_sha256" in {i["name"] for i in inspector.get_indexes("uploads")}
    assert "ix_transactions_upload_id_transaction_date" in {i["name"] for i in inspector.get_indexes("transactions")}
    assert "uq_budgets_user_category" in {c["name"] for c in inspector.get_unique_constraints("budgets")}
    assert "uq_analysis_runs_upload_module" in {c["name"] for c in inspector.get_unique_constraints("analysis_runs")}
    assert "uq_analysis_results_upload_type" in {c["name"] for c in inspector.get_unique_constraints("analysis_results")}
    users_indexes = {i["name"]: i for i in inspector.get_indexes("users")}
    assert users_indexes["ix_users_email"]["unique"]


def test_migration_downgrade_and_upgrade_round_trip(test_engine):
    config = _alembic_config(TEST_DATABASE_URL)
    command.downgrade(config, "base")
    assert not EXPECTED_TABLES & set(inspect(test_engine).get_table_names())
    command.upgrade(config, "head")
    assert EXPECTED_TABLES.issubset(set(inspect(test_engine).get_table_names()))
