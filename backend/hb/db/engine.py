"""Engine/session factory. WAL mode + foreign keys enforced on every connection."""

from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from hb.config import settings

_engine: Engine | None = None


def _configure_sqlite(dbapi_conn, _record) -> None:
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    # Wait up to 5s for a write lock instead of failing instantly with
    # "database is locked" — lets the API, the daily scan, and one-off pipeline
    # commands write concurrently (WAL allows one writer at a time).
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.close()


def make_engine(db_path: Path | str | None = None) -> Engine:
    """Build a fresh engine (tests pass a tmp path); ensures the parent dir exists."""
    path = Path(db_path) if db_path else settings.db_path
    path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"sqlite:///{path}")
    event.listen(engine, "connect", _configure_sqlite)
    return engine


def get_engine() -> Engine:
    """Process-wide default engine bound to settings.db_path."""
    global _engine
    if _engine is None:
        _engine = make_engine()
    return _engine


def make_session(engine: Engine | None = None) -> Session:
    return sessionmaker(bind=engine or get_engine(), expire_on_commit=False)()
