"""Tests for plan -> tool capability enforcement."""

from __future__ import annotations

import pytest

from mezake_mcp.auth.policy import (
    ToolNotAllowedError,
    category_for,
    check_tool_allowed,
    invalidate_plan,
    plan_for_user,
    reset_cache,
)
from mezake_mcp.storage.db import session_scope
from mezake_mcp.storage.models import Tenant, User


def _seed(plan: str, email: str = "u@example.com") -> int:
    reset_cache()
    with session_scope() as session:
        tenant = Tenant(name="T", plan=plan)
        session.add(tenant)
        session.flush()
        user = User(tenant_id=tenant.id, email=email)
        session.add(user)
        session.flush()
        return user.id


class TestCategoryFor:
    def test_known_read_tool(self) -> None:
        assert category_for("odoo_search_read") == "read"

    def test_known_write_tool(self) -> None:
        assert category_for("odoo_create") == "write"

    def test_known_delete_tool(self) -> None:
        assert category_for("odoo_unlink") == "delete"

    def test_unclassified_tool_defaults_to_write(self) -> None:
        # Safer default — never accidentally gives read-only plans new tools.
        assert category_for("totally_unknown_tool") == "write"


class TestPlanResolution:
    def test_plan_for_user_loads_from_db(self, inmemory_db) -> None:
        uid = _seed("pro")
        assert plan_for_user(uid) == "pro"

    def test_unknown_user_defaults_to_free(self, inmemory_db) -> None:
        reset_cache()
        assert plan_for_user(99999) == "free"

    def test_cache_avoids_second_db_query(self, inmemory_db) -> None:
        uid = _seed("enterprise")
        plan1 = plan_for_user(uid)
        # Mutate the row but don't invalidate the cache
        with session_scope() as session:
            from sqlalchemy import update
            session.execute(update(Tenant).values(plan="free"))
        assert plan_for_user(uid) == plan1  # still "enterprise" from cache

    def test_invalidate_picks_up_changes(self, inmemory_db) -> None:
        uid = _seed("free")
        assert plan_for_user(uid) == "free"
        with session_scope() as session:
            from sqlalchemy import update
            session.execute(update(Tenant).values(plan="enterprise"))
        invalidate_plan(uid)
        assert plan_for_user(uid) == "enterprise"


class TestCheckToolAllowed:
    def test_free_plan_can_read(self, inmemory_db) -> None:
        uid = _seed("free")
        check_tool_allowed(uid, "odoo_search_read")  # no raise

    def test_free_plan_cannot_write(self, inmemory_db) -> None:
        uid = _seed("free")
        with pytest.raises(ToolNotAllowedError, match="write"):
            check_tool_allowed(uid, "odoo_create")

    def test_free_plan_cannot_delete(self, inmemory_db) -> None:
        uid = _seed("free")
        with pytest.raises(ToolNotAllowedError, match="delete"):
            check_tool_allowed(uid, "odoo_unlink")

    def test_pro_plan_can_write_but_not_delete(self, inmemory_db) -> None:
        uid = _seed("pro")
        check_tool_allowed(uid, "odoo_create")  # no raise
        with pytest.raises(ToolNotAllowedError):
            check_tool_allowed(uid, "odoo_unlink")

    def test_enterprise_can_do_everything(self, inmemory_db) -> None:
        uid = _seed("enterprise")
        check_tool_allowed(uid, "odoo_search_read")
        check_tool_allowed(uid, "odoo_create")
        check_tool_allowed(uid, "odoo_unlink")

    def test_self_hosted_can_do_everything(self, inmemory_db) -> None:
        uid = _seed("self-hosted")
        check_tool_allowed(uid, "odoo_unlink")

    def test_no_user_id_passes_through(self, inmemory_db) -> None:
        # Stdio / dev / tests outside the request scope.
        check_tool_allowed(None, "odoo_unlink")  # no raise

    def test_unknown_plan_defaults_to_free(self, inmemory_db) -> None:
        uid = _seed("custom-tier-not-defined")
        check_tool_allowed(uid, "odoo_search")  # read works
        with pytest.raises(ToolNotAllowedError):
            check_tool_allowed(uid, "odoo_create")
