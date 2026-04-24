"""Tests for the user_id -> OdooClient resolver + cache."""

from __future__ import annotations

import pytest

from mezake_mcp.auth.crypto import encrypt
from mezake_mcp.auth.resolver import (
    NoConnectionError,
    invalidate_user,
    load_client_for_user,
    reset_cache,
)
from mezake_mcp.storage.db import session_scope
from mezake_mcp.storage.models import OdooConnection, Tenant, User


@pytest.fixture
def seeded_user(inmemory_db, encryption_key):
    reset_cache()
    with session_scope() as session:
        tenant = Tenant(name="Default", plan="self-hosted")
        session.add(tenant)
        session.flush()
        user = User(tenant_id=tenant.id, email="user@example.com")
        session.add(user)
        session.flush()
        session.add(OdooConnection(
            user_id=user.id,
            url="https://acme.odoo.com",
            db="acme-prod",
            login="user@example.com",
            api_key_encrypted=encrypt("raw-secret"),
        ))
        uid = user.id
    yield uid
    reset_cache()


class TestLoad:
    def test_builds_client_from_stored_connection(self, seeded_user) -> None:
        client = load_client_for_user(seeded_user)
        assert client._url == "https://acme.odoo.com"
        assert client._db == "acme-prod"
        assert client._login == "user@example.com"
        assert client._api_key == "raw-secret"

    def test_missing_connection_raises(self, inmemory_db, encryption_key) -> None:
        reset_cache()
        with pytest.raises(NoConnectionError):
            load_client_for_user(9999)

    def test_same_user_returns_same_client_instance(self, seeded_user) -> None:
        c1 = load_client_for_user(seeded_user)
        c2 = load_client_for_user(seeded_user)
        assert c1 is c2


class TestInvalidate:
    def test_invalidate_forces_rebuild(self, seeded_user) -> None:
        c1 = load_client_for_user(seeded_user)
        invalidate_user(seeded_user)
        c2 = load_client_for_user(seeded_user)
        assert c1 is not c2

    def test_invalidate_unknown_is_silent(self, seeded_user) -> None:
        invalidate_user(9999)  # must not raise
