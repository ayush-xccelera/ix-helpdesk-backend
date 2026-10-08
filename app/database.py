"""SQLAlchemy 2.x engine/session management and idempotent schema bootstrap."""
from __future__ import annotations

import logging
from collections.abc import Iterator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import settings

logger = logging.getLogger("app.database")


class Base(DeclarativeBase):
    """Declarative base shared by every ORM model."""


engine = create_engine(settings.DATABASE_URL, pool_pre_ping=True, future=True)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)

TICKET_NUMBER_SEQUENCE = "ticket_number_seq"


def get_db() -> Iterator[Session]:
    """FastAPI dependency yielding a request-scoped database session.

    Commits once, automatically, after a request completes without error;
    rolls back on any exception. This keeps routers/services from ever
    needing to call `db.commit()` themselves.
    """
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def init_db() -> None:
    """Create the database schema automatically and idempotently (no manual migrations)."""
    # Import here (not at module load) to avoid a circular import between
    # database.py and models.py while still registering all mapped classes
    # on Base.metadata before create_all runs.
    from app import models  # noqa: F401

    Base.metadata.create_all(bind=engine)

    with engine.begin() as connection:
        connection.execute(text(f"CREATE SEQUENCE IF NOT EXISTS {TICKET_NUMBER_SEQUENCE} START 1"))

    logger.info("database schema initialized")
