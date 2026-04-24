"""SQLAlchemy engine + session factory.

Initialization is lazy: `init()` is a no-op when `DATABASE_URL` isn't set,
so the server still boots without a Postgres attached. Later phases that
actually persist state should call `is_enabled()` and fall back gracefully
(or error clearly) when storage is off.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from mezake_mcp.config import get_settings

log = logging.getLogger(__name__)


_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None
_lock = threading.Lock()


def normalize_dsn(dsn: str) -> str:
    """Coerce legacy / Heroku-style DSNs to the `postgresql+psycopg://` form
    SQLAlchemy wants when `psycopg` (v3) is the installed driver.

    Transformations applied:
      postgres://…            → postgresql://…      (old Heroku form)
      postgresql://…          → postgresql+psycopg://…
      postgresql+psycopg2://… → left alone (explicit opt-in to psycopg2)
    """
    if dsn.startswith("postgres://"):
        dsn = "postgresql://" + dsn[len("postgres://") :]
    if dsn.startswith("postgresql://") and not dsn.startswith("postgresql+"):
        dsn = "postgresql+psycopg://" + dsn[len("postgresql://") :]
    return dsn


def init() -> None:
    """Create the global engine + session factory.

    Idempotent. No-op if `DATABASE_URL` isn't configured.
    """
    global _engine, _SessionLocal
    if _engine is not None:
        return
    with _lock:
        if _engine is not None:
            return
        settings = get_settings()
        if not settings.database_url:
            log.info("DATABASE_URL not set; storage disabled for this process")
            return
        dsn = normalize_dsn(settings.database_url)
        _engine = create_engine(dsn, pool_pre_ping=True, future=True)
        _SessionLocal = sessionmaker(bind=_engine, autoflush=False, expire_on_commit=False)
        log.info("Storage engine initialized")


def is_enabled() -> bool:
    """Whether storage was successfully initialized."""
    return _engine is not None


def get_engine() -> Engine:
    """Return the global engine. Raises if storage is disabled."""
    if _engine is None:
        raise RuntimeError(
            "Storage not initialized. Set DATABASE_URL and call storage.init()."
        )
    return _engine


@contextmanager
def session_scope() -> Iterator[Session]:
    """Context-managed session with commit/rollback semantics.

    ```
    with session_scope() as session:
        session.add(User(...))
    ```
    """
    if _SessionLocal is None:
        raise RuntimeError(
            "Storage not initialized. Set DATABASE_URL and call storage.init()."
        )
    session = _SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
