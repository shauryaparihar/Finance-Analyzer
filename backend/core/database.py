"""
Database engine, session factory and declarative base.

The schema is owned by Alembic migrations (see backend/migrations); nothing here creates tables.
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from backend.core.config import DATABASE_URL

# TCP keepalives stop routers and hosted databases from silently dropping a connection that is quiet for a few minutes.
engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    connect_args={"keepalives": 1, "keepalives_idle": 30, "keepalives_interval": 10, "keepalives_count": 5},
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    """Yield a database session for one request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
