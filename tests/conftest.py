"""Shared pytest fixtures.

Two things worth knowing:

1. `_inmemory_db` swaps the module-level `_engine` / `_SessionLocal` with
   an in-memory SQLite. We use `StaticPool` so every session in a test
   shares the same single connection — otherwise SQLite's default pool
   gives each session its own private in-memory DB and nothing you
   insert is visible to anything else.

2. `encryption_key` sets ENCRYPTION_KEY for the duration of one test,
   busts the cached `Settings` object (it's `@lru_cache`d) and the
   cached Fernet (also lru-cached), then restores both after.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from mezake_mcp.config import get_settings
from mezake_mcp.storage import db as storage_db
from mezake_mcp.storage.models import Base


@pytest.fixture
def inmemory_db(monkeypatch):
    """Wire an in-memory SQLite DB into the storage module for one test."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    session_local = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    monkeypatch.setattr(storage_db, "_engine", engine)
    monkeypatch.setattr(storage_db, "_SessionLocal", session_local)

    yield engine

    Base.metadata.drop_all(engine)


@pytest.fixture
def encryption_key(monkeypatch):
    """Set a fresh ENCRYPTION_KEY and bust the settings/fernet caches."""
    from cryptography.fernet import Fernet

    from mezake_mcp.auth import crypto

    key = Fernet.generate_key().decode()
    monkeypatch.setenv("ENCRYPTION_KEY", key)
    get_settings.cache_clear()
    crypto.reset_cache()

    yield key

    get_settings.cache_clear()
    crypto.reset_cache()
