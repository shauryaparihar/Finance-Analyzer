import threading

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from backend import migrate
from backend.core.config import BASE_DIR
from backend.tests.conftest import TEST_DATABASE_URL

LOCK_DB = "finsight_lock_test"


@pytest.fixture
def empty_database():
    base = make_url(TEST_DATABASE_URL)
    admin = create_engine(base.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{LOCK_DB}" WITH (FORCE)'))
        conn.execute(text(f'CREATE DATABASE "{LOCK_DB}"'))
    yield base.set(database=LOCK_DB).render_as_string(hide_password=False)
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{LOCK_DB}" WITH (FORCE)'))
    admin.dispose()


def test_instances_starting_together_take_turns_and_all_succeed(empty_database):
    errors: list[BaseException] = []

    def start_instance():
        try:
            migrate.run(empty_database)
        except BaseException as e:  # noqa: BLE001 - the test reports any failure
            errors.append(e)

    threads = [threading.Thread(target=start_instance) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=120)
    assert errors == []
    engine = create_engine(empty_database)
    with engine.connect() as conn:
        assert conn.scalar(text("SELECT version_num FROM alembic_version")) == ScriptDirectory.from_config(Config(str(BASE_DIR / "alembic.ini"))).get_current_head()
        assert conn.scalar(text("SELECT count(*) FROM information_schema.tables WHERE table_name = 'users'")) == 1
    engine.dispose()


def test_running_it_again_on_an_up_to_date_database_does_nothing(empty_database):
    migrate.run(empty_database)
    migrate.run(empty_database)
