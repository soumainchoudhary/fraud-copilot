"""Database engine and session management supporting SQLite and PostgreSQL."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Generator

import structlog
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, declarative_base, sessionmaker
from sqlalchemy.pool import QueuePool, StaticPool

from app.config import get_settings

logger = structlog.get_logger(__name__)

Base = declarative_base()

_engine = None
_SessionFactory = None


def get_engine():
    """Retrieve or create the SQLAlchemy engine with appropriate dialect tuning."""
    global _engine, _SessionFactory
    if _engine is not None:
        return _engine

    settings = get_settings()
    db_url = os.getenv("DATABASE_URL", settings.database_url)

    connect_args = {}
    pool_kwargs = {}

    if db_url.startswith("sqlite"):
        connect_args["check_same_thread"] = False
        if ":memory:" in db_url:
            pool_kwargs["poolclass"] = StaticPool
        else:
            # Ensure SQLite data directory exists
            if "///" in db_url:
                db_path = db_url.split("///")[-1]
                Path(db_path).parent.mkdir(parents=True, exist_ok=True)

        _engine = create_engine(
            db_url,
            connect_args=connect_args,
            **pool_kwargs,
        )

        # Enable SQLite foreign keys & WAL mode for high concurrency
        @event.listens_for(_engine, "connect")
        def _set_sqlite_pragma(dbapi_connection, connection_record):
            cursor = dbapi_connection.cursor()
            try:
                cursor.execute("PRAGMA journal_mode=WAL")
                cursor.execute("PRAGMA synchronous=NORMAL")
                cursor.execute("PRAGMA foreign_keys=ON")
            except Exception:
                pass
            finally:
                cursor.close()
    else:
        # PostgreSQL / MySQL enterprise pooling
        _engine = create_engine(
            db_url,
            poolclass=QueuePool,
            pool_size=10,
            max_overflow=20,
            pool_pre_ping=True,
        )

    _SessionFactory = sessionmaker(autocommit=False, autoflush=False, bind=_engine)
    logger.info("database_engine_initialized", dialect=_engine.dialect.name)
    return _engine


def get_session_factory():
    """Retrieve the session factory."""
    global _SessionFactory
    if _SessionFactory is None:
        get_engine()
    return _SessionFactory


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency yielding a transactional DB session."""
    session_factory = get_session_factory()
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


def init_db(engine=None) -> None:
    """Create all registered tables if they do not exist."""
    eng = engine or get_engine()
    Base.metadata.create_all(bind=eng)
    logger.info("database_tables_verified")
