"""Tests for the env-var -> DB bootstrap."""

from __future__ import annotations

from sqlalchemy import func, select

from mezake_mcp.auth.bootstrap import bootstrap_default_user
from mezake_mcp.auth.crypto import decrypt
from mezake_mcp.config import get_settings
from mezake_mcp.storage.db import session_scope
from mezake_mcp.storage.models import OdooConnection, Tenant, User


def _set_env(monkeypatch) -> None:
    monkeypatch.setenv("ODOO_URL", "https://example.odoo.com")
    monkeypatch.setenv("ODOO_DB", "example-db")
    monkeypatch.setenv("ODOO_USER", "admin@example.com")
    monkeypatch.setenv("ODOO_API_KEY", "super-secret-key")
    get_settings.cache_clear()


class TestBootstrap:
    def test_seeds_tenant_user_and_connection(
        self, inmemory_db, encryption_key, monkeypatch
    ) -> None:
        _set_env(monkeypatch)

        bootstrap_default_user()

        with session_scope() as session:
            assert session.scalar(select(func.count()).select_from(Tenant)) == 1
            assert session.scalar(select(func.count()).select_from(User)) == 1
            assert session.scalar(select(func.count()).select_from(OdooConnection)) == 1

            tenant = session.scalar(select(Tenant))
            assert tenant.name == "Default"
            assert tenant.plan == "self-hosted"

            user = session.scalar(select(User))
            assert user.email == "admin@example.com"
            assert user.tenant_id == tenant.id

            connection = session.scalar(select(OdooConnection))
            assert connection.user_id == user.id
            assert connection.url == "https://example.odoo.com"
            assert connection.db == "example-db"
            assert connection.login == "admin@example.com"
            # API key is stored encrypted, never as plaintext
            assert connection.api_key_encrypted != "super-secret-key"
            assert decrypt(connection.api_key_encrypted) == "super-secret-key"

    def test_idempotent_on_second_run(
        self, inmemory_db, encryption_key, monkeypatch
    ) -> None:
        _set_env(monkeypatch)

        bootstrap_default_user()
        bootstrap_default_user()

        with session_scope() as session:
            assert session.scalar(select(func.count()).select_from(User)) == 1
            assert session.scalar(select(func.count()).select_from(Tenant)) == 1

    def test_skips_when_encryption_key_missing(
        self, inmemory_db, monkeypatch
    ) -> None:
        _set_env(monkeypatch)
        monkeypatch.delenv("ENCRYPTION_KEY", raising=False)
        get_settings.cache_clear()

        bootstrap_default_user()  # Should not raise, just skip

        with session_scope() as session:
            assert session.scalar(select(func.count()).select_from(User)) == 0

    def test_skips_when_odoo_env_incomplete(
        self, inmemory_db, encryption_key, monkeypatch
    ) -> None:
        monkeypatch.setenv("ODOO_URL", "https://example.odoo.com")
        monkeypatch.delenv("ODOO_API_KEY", raising=False)
        monkeypatch.setenv("ODOO_DB", "example-db")
        monkeypatch.setenv("ODOO_USER", "admin@example.com")
        get_settings.cache_clear()

        bootstrap_default_user()

        with session_scope() as session:
            assert session.scalar(select(func.count()).select_from(User)) == 0
