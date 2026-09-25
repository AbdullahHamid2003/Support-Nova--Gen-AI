"""SQLAlchemy engine/session management and the declarative base.

PostgreSQL is the primary database (JSONB columns, trigram-capable text, an
immutability trigger on audit_logs). SQLite is supported for zero-dependency
unit tests only.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, MetaData, create_engine, event, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from supportnova.core.config import get_settings

NAMING = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

JSONType = JSON().with_variant(JSONB(), "postgresql")


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING)
    type_annotation_map = {dict[str, Any]: JSONType, list[Any]: JSONType}  # noqa: RUF012 (SQLAlchemy API)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None


def get_engine() -> Engine:
    global _engine, _SessionLocal
    if _engine is None:
        settings = get_settings()
        kwargs: dict[str, Any] = {"echo": settings.db_echo, "future": True}
        if settings.is_sqlite:
            kwargs["connect_args"] = {"check_same_thread": False}
        else:
            kwargs.update(pool_size=10, max_overflow=20, pool_pre_ping=True, pool_recycle=1800)
        _engine = create_engine(settings.database_url, **kwargs)
        if settings.is_sqlite:
            @event.listens_for(_engine, "connect")
            def _sqlite_pragmas(dbapi_conn: Any, _record: Any) -> None:  # pragma: no cover - sqlite only
                cur = dbapi_conn.cursor()
                cur.execute("PRAGMA foreign_keys=ON")
                cur.execute("PRAGMA journal_mode=WAL")
                cur.close()
        _SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False, autoflush=False)
    return _engine


def reset_engine(url: str | None = None) -> None:
    """Dispose the engine (tests switch databases through this)."""
    global _engine, _SessionLocal
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _SessionLocal = None
    if url:
        get_settings().database_url = url


def session_factory() -> sessionmaker[Session]:
    get_engine()
    assert _SessionLocal is not None
    return _SessionLocal


@contextmanager
def session_scope() -> Iterator[Session]:
    """Transactional scope for background jobs and scripts."""
    session = session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_db() -> Iterator[Session]:
    """FastAPI dependency: one session per request, committed by the service layer."""
    session = session_factory()()
    try:
        yield session
    finally:
        session.close()
