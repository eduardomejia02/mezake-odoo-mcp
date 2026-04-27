"""Tests for admin-role helpers + audit query helper.

The HTTP routes themselves are exercised by integration tests against
the deployed Railway service; here we cover the building blocks.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from mezake_mcp import audit
from mezake_mcp.auth.admin import is_admin_email, is_current_user_admin
from mezake_mcp.auth.context import current_user_id
from mezake_mcp.config import get_settings
from mezake_mcp.storage.db import session_scope
from mezake_mcp.storage.models import Tenant, User


@pytest.fixture
def admin_emails(monkeypatch):
    monkeypatch.setenv("ADMIN_EMAILS", "boss@example.com, admin2@example.com")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _seed(email: str) -> int:
    with session_scope() as session:
        tenant = Tenant(name="T", plan="self-hosted")
        session.add(tenant)
        session.flush()
        user = User(tenant_id=tenant.id, email=email)
        session.add(user)
        session.flush()
        return user.id


class TestIsAdminEmail:
    def test_listed_email_is_admin(self, admin_emails) -> None:
        assert is_admin_email("boss@example.com") is True

    def test_case_insensitive(self, admin_emails) -> None:
        assert is_admin_email("BOSS@example.COM") is True

    def test_handles_whitespace(self, admin_emails) -> None:
        assert is_admin_email("  admin2@example.com ") is True

    def test_unlisted_is_not_admin(self, admin_emails) -> None:
        assert is_admin_email("random@example.com") is False

    def test_empty_email_is_not_admin(self, admin_emails) -> None:
        assert is_admin_email("") is False

    def test_no_admin_emails_configured(self, monkeypatch) -> None:
        monkeypatch.delenv("ADMIN_EMAILS", raising=False)
        get_settings.cache_clear()
        assert is_admin_email("anyone@example.com") is False


class TestIsCurrentUserAdmin:
    def test_unauthenticated_request_is_not_admin(self, inmemory_db, admin_emails) -> None:
        # No contextvar set
        assert is_current_user_admin() is False

    def test_authenticated_admin_user(self, inmemory_db, admin_emails) -> None:
        uid = _seed("boss@example.com")
        token = current_user_id.set(uid)
        try:
            assert is_current_user_admin() is True
        finally:
            current_user_id.reset(token)

    def test_authenticated_non_admin_user(self, inmemory_db, admin_emails) -> None:
        uid = _seed("regular@example.com")
        token = current_user_id.set(uid)
        try:
            assert is_current_user_admin() is False
        finally:
            current_user_id.reset(token)


class TestListRecent:
    def test_empty_when_no_rows(self, inmemory_db) -> None:
        assert audit.list_recent() == []

    def test_returns_dicts_with_iso_timestamps(self, inmemory_db) -> None:
        uid = _seed("u@example.com")
        audit.record_call(uid, "odoo_search", status="ok", duration_ms=10)
        rows = audit.list_recent()
        assert len(rows) == 1
        r = rows[0]
        assert r["tool_name"] == "odoo_search"
        assert r["status"] == "ok"
        assert r["duration_ms"] == 10
        assert r["created_at"] is not None
        # Must be parseable back into a datetime
        datetime.fromisoformat(r["created_at"])

    def test_filters_by_user_id(self, inmemory_db) -> None:
        uid_a = _seed("a@example.com")
        uid_b = _seed("b@example.com")
        audit.record_call(uid_a, "tool_a", status="ok", duration_ms=1)
        audit.record_call(uid_b, "tool_b", status="ok", duration_ms=1)
        rows = audit.list_recent(user_id=uid_a)
        assert len(rows) == 1
        assert rows[0]["tool_name"] == "tool_a"

    def test_filters_by_tool_name(self, inmemory_db) -> None:
        uid = _seed("u@example.com")
        audit.record_call(uid, "odoo_search", status="ok", duration_ms=1)
        audit.record_call(uid, "odoo_create", status="ok", duration_ms=1)
        rows = audit.list_recent(tool_name="odoo_search")
        assert len(rows) == 1
        assert rows[0]["tool_name"] == "odoo_search"

    def test_filters_by_status(self, inmemory_db) -> None:
        uid = _seed("u@example.com")
        audit.record_call(uid, "t", status="ok", duration_ms=1)
        audit.record_call(uid, "t", status="error", duration_ms=1, error="boom")
        audit.record_call(uid, "t", status="denied", duration_ms=0, error="no")
        assert len(audit.list_recent(status="error")) == 1
        assert len(audit.list_recent(status="denied")) == 1

    def test_filters_by_since(self, inmemory_db) -> None:
        uid = _seed("u@example.com")
        audit.record_call(uid, "t", status="ok", duration_ms=1)
        future = datetime.now(timezone.utc) + timedelta(minutes=1)
        assert audit.list_recent(since=future) == []

    def test_limit_caps_returned_rows(self, inmemory_db) -> None:
        uid = _seed("u@example.com")
        for _ in range(5):
            audit.record_call(uid, "t", status="ok", duration_ms=1)
        assert len(audit.list_recent(limit=3)) == 3
