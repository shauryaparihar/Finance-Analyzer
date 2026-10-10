"""
Bring the database up to date, safely when several server instances start at the same moment.

    python -m backend.migrate

The Docker image runs this before starting the API. A PostgreSQL advisory lock makes the instances take turns:
the first applies any pending migrations, the others wait, then find nothing left to do. Without the lock two
instances could both try to create the same table and one would crash on start.
"""
import sys

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

from backend.core.config import BASE_DIR, settings

LOCK_KEY = 726_001_001  # any fixed number; every instance must use the same one


def run(url: str | None = None) -> None:
    url = url or settings.database_url
    config = Config(str(BASE_DIR / "alembic.ini"))
    config.attributes["database_url"] = url
    # The lock belongs to this connection, so it stays held while Alembic works on its own connection.
    engine = create_engine(url, isolation_level="AUTOCOMMIT")
    with engine.connect() as lock_connection:
        lock_connection.execute(text("SELECT pg_advisory_lock(:key)"), {"key": LOCK_KEY})
        try:
            command.upgrade(config, "head")
        finally:
            lock_connection.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": LOCK_KEY})
    engine.dispose()


if __name__ == "__main__":
    run()
    print("database is up to date", file=sys.stderr)
