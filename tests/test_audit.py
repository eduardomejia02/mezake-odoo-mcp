"""Tests for audit log writes."""

from __future__ import annotations

from sqlalchemy import select

from mezake_mcp.audit import record_call
from mezake_mcp.storage.db import session_scope
from mezake_mcp.storage.models import AuditLog, Tenant, User


def _seed_user(email: str = "u@example.com") -> int:
    with session_scope() as session:
        tenant = Tenant(name="Default", plan="self-hosted")
        session.add(tenant)
        session.flush()
        user = User(tenant_id=tenant.id, email=email)
        session.add(user)
        session.flush()
        return user.id


class TestRecordCall:
    def test_writes_an_ok_row(self, inmemory_db) -> None:
        uid = _seed_user()
        record_call(uid, "odoo_search", status="ok", duration_ms=42,
                    odoo_model="account.move")
        with session_scope() as session:
            row = session.scalar(select(AuditLog))
            assert row is not None
            assert row.user_id == uid
            assert row.tool_name == "odoo_search"
            assert row.status == "ok"
            assert row.duration_ms == 42
            assert row.odoo_model == "account.move"
            assert row.odoo_method is None
            assert row.error is None

    def test_writes_an_error_row(self, inmemory_db) -> None:
        uid = _seed_user()
        record_call(uid, "odoo_create", status="error", duration_ms=120,
                    odoo_model="res.partner",
                    error="Validation failed: name required")
        with session_scope() as session:
            row = session.scalar(select(AuditLog))
            assert row.status == "error"
            assert "name required" in row.error

    def test_no_op_when_storage_disabled(self, monkeypatch) -> None:
        # Force storage off without using the inmemory_db fixture
        from mezake_mcp.storage import db as storage_db
        monkeypatch.setattr(storage_db, "_engine", None)
        monkeypatch.setattr(storage_db, "_SessionLocal", None)
        # Must not raise
        record_call(None, "odoo_read", status="ok", duration_ms=1)

    def test_user_id_can_be_null(self, inmemory_db) -> None:
        record_call(None, "anonymous_tool", status="ok", duration_ms=5)
        with session_scope() as session:
            row = session.scalar(select(AuditLog))
            assert row is not None
            assert row.user_id is None
            assert row.tool_name == "anonymous_tool"

    def test_error_message_is_truncated(self, inmemory_db) -> None:
        uid = _seed_user()
        long_msg = "x" * 5000
        record_call(uid, "odoo_call", status="error", duration_ms=1,
                    error=long_msg)
        with session_scope() as session:
            row = session.scalar(select(AuditLog))
            assert len(row.error) <= 1000
