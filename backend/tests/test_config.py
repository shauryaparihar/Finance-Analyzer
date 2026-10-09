import pytest
from pydantic import ValidationError

from backend.core.config import Settings


def test_postgres_urls_are_normalized_to_psycopg3():
    assert Settings(database_url="postgres://u:p@h/db").database_url == "postgresql+psycopg://u:p@h/db"
    assert Settings(database_url="postgresql://u:p@h/db").database_url == "postgresql+psycopg://u:p@h/db"


def test_empty_database_url_falls_back_to_default():
    assert Settings(database_url="").database_url.startswith("postgresql+psycopg://")


def test_non_postgres_database_is_rejected():
    with pytest.raises(ValidationError):
        Settings(database_url="sqlite:///x.db")
