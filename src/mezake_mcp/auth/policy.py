"""Per-plan tool allow-lists.

Every tenant has a `plan` string. Each plan grants a set of capability
tags ("read", "write", "delete"). Each tool is classified as one of
those tags. A tool call is allowed iff the tenant's plan grants the
tool's tag.

Reasoning:
  - Free / trial users get read-only access — a Claude session can
    explore the data but can't damage anything.
  - Paid plans add writes; enterprise adds destructive deletes.
  - The `self-hosted` plan (the bootstrap default — what a single-tenant
    deployment uses for its operator) gets everything.

This file is the only place to update when adding or re-classifying
tools. Unknown tools default to `"write"` so nothing is mistakenly
opened up to the read-only tier without explicit thought.
"""

from __future__ import annotations

import logging
import threading
from functools import lru_cache

from sqlalchemy import select

from mezake_mcp.storage.db import is_enabled, session_scope
from mezake_mcp.storage.models import Tenant, User

log = logging.getLogger(__name__)


# ── Capability tags ───────────────────────────────────────────────────────────

READ = "read"
WRITE = "write"
DELETE = "delete"

PLAN_CAPABILITIES: dict[str, set[str]] = {
    "free": {READ},
    "pro": {READ, WRITE},
    "enterprise": {READ, WRITE, DELETE},
    "self-hosted": {READ, WRITE, DELETE},
}


# ── Tool classification ───────────────────────────────────────────────────────
# Generic ORM tools first, then the curated legacy ones. Anything not in
# this map is treated as WRITE (safer default than READ).

TOOL_CATEGORY: dict[str, str] = {
    # Generic ORM
    "odoo_list_models": READ,
    "odoo_describe_model": READ,
    "odoo_search": READ,
    "odoo_search_read": READ,
    "odoo_read": READ,
    "odoo_read_group": READ,
    "odoo_create": WRITE,
    "odoo_write": WRITE,
    "odoo_translate_field": WRITE,
    "odoo_unlink": DELETE,
    # `odoo_call` is the catch-all — it can confirm an invoice or unlink a
    # record. Bucket as WRITE; users on the read-only plan can't reach it,
    # users on pro can call most workflow methods, but the safest path for
    # a destructive method is still through `odoo_unlink` which enterprise
    # gates on DELETE.
    "odoo_call": WRITE,

    # Legacy reads
    "get_active_company": READ,
    "get_dashboard": READ,
    "get_pipeline_summary": READ,
    "search_leads": READ,
    "get_utm_sources": READ,
    "search_contacts": READ,
    "get_accounting_summary": READ,
    "get_invoices": READ,
    "get_revenue_report": READ,
    "list_employees": READ,
    "get_leaves": READ,
    "list_payslips": READ,
    "get_payroll_summary": READ,
    "search_products": READ,
    "get_low_stock_alert": READ,
    "get_whatsapp_messages": READ,
    "list_whatsapp_chatbots": READ,
    "get_chatbot_steps": READ,
    "list_projects": READ,
    "list_tasks": READ,
    "get_website_leads": READ,
    "get_sales_orders": READ,
    "list_social_accounts": READ,
    "list_social_campaigns": READ,
    "list_social_posts": READ,
    "get_social_campaign_stats": READ,
    "explore_social_ads_fields": READ,

    # Legacy writes
    "create_lead": WRITE,
    "update_lead": WRITE,
    "mark_lead_won": WRITE,
    "mark_lead_lost": WRITE,
    "log_lead_note": WRITE,
    "schedule_activity": WRITE,
    "create_contact": WRITE,
    "update_contact": WRITE,
    "create_invoice": WRITE,
    "confirm_invoice": WRITE,
    "mark_invoice_paid": WRITE,
    "create_bulk_journal_entry": WRITE,
    "create_employee": WRITE,
    "approve_leave": WRITE,
    "refuse_leave": WRITE,
    "create_payslip": WRITE,
    "confirm_payslip": WRITE,
    "send_whatsapp_message": WRITE,
    "create_chatbot_step": WRITE,
    "create_task": WRITE,
    "create_social_campaign": WRITE,
    "create_social_post": WRITE,
    "delete_social_post": DELETE,
}


def category_for(tool_name: str) -> str:
    """Return the capability tag for `tool_name`. Defaults to WRITE for
    unclassified tools so accidentally-added tools aren't auto-allowed
    on the read-only tier.
    """
    return TOOL_CATEGORY.get(tool_name, WRITE)


# ── Errors ────────────────────────────────────────────────────────────────────

class ToolNotAllowedError(PermissionError):
    """Raised when the caller's plan doesn't include the tool's capability."""


# ── Plan resolution (cached per user) ─────────────────────────────────────────

_plan_cache: dict[int, str] = {}
_plan_cache_lock = threading.Lock()


def plan_for_user(user_id: int) -> str:
    """Return the tenant.plan string for a user. Cached process-wide so
    every tool call doesn't re-query Postgres.
    """
    cached = _plan_cache.get(user_id)
    if cached is not None:
        return cached
    with _plan_cache_lock:
        cached = _plan_cache.get(user_id)
        if cached is not None:
            return cached
        with session_scope() as session:
            row = session.execute(
                select(Tenant.plan)
                .join(User, User.tenant_id == Tenant.id)
                .where(User.id == user_id)
            ).scalar_one_or_none()
            plan = row or "free"
        _plan_cache[user_id] = plan
        return plan


def invalidate_plan(user_id: int) -> None:
    """Drop the cached plan for `user_id`. Call after upgrading the tenant."""
    with _plan_cache_lock:
        _plan_cache.pop(user_id, None)


def reset_cache() -> None:
    """Clear the entire cache. For tests only."""
    with _plan_cache_lock:
        _plan_cache.clear()


# ── Authorization check ───────────────────────────────────────────────────────

def check_tool_allowed(user_id: int | None, tool_name: str) -> None:
    """Raise `ToolNotAllowedError` if the user's plan doesn't grant the
    tool's capability. Pass-through if `user_id` is None (stdio / dev).

    No-op when storage is disabled — there's no plan info to consult.
    """
    if user_id is None:
        return
    if not is_enabled():
        return
    needed = category_for(tool_name)
    plan = plan_for_user(user_id)
    granted = PLAN_CAPABILITIES.get(plan, PLAN_CAPABILITIES["free"])
    if needed not in granted:
        raise ToolNotAllowedError(
            f"Tool '{tool_name}' requires '{needed}' capability; "
            f"your plan '{plan}' grants {sorted(granted)}."
        )
