"""
Database engine, session factory and declarative base.

The schema is owned by Alembic migrations (see backend/migrations); nothing here creates tables.
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from backend.core.config import DATABASE_URL

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
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
