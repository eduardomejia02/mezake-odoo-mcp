"""Audit log writes + read helpers.

Every tool invocation that flows through `auth.wrap.wrap_all_tools()`
gets a row written here on completion. Failures are recorded too — the
audit log is the source of truth for "what happened, when, by whom,
how long, what went wrong".

Design notes:
  - Synchronous writes. Postgres is fast and tool calls are not
    millisecond-sensitive at human-driven AI rates. If volume ever
    pushes past a few hundred QPS, move to a background queue.
  - No-op when storage is disabled (stdio / local dev). The decision
    not to log shouldn't crash a tool call.
  - We never raise from `record_call`. Audit failures get logged at
    WARNING and the tool call still returns its result.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from sqlalchemy import select

from mezake_mcp.storage.db import is_enabled, session_scope
from mezake_mcp.storage.models import AuditLog

log = logging.getLogger(__name__)


def record_call(
    user_id: int | None,
    tool_name: str,
    status: str,
    duration_ms: int,
    *,
    odoo_model: str | None = None,
    odoo_method: str | None = None,
    error: str | None = None,
) -> None:
    """Persist one audit row. Fully best-effort — any failure is logged
    but does not raise.
    """
    if not is_enabled():
        return
    try:
        with session_scope() as session:
            session.add(AuditLog(
                user_id=user_id,
                tool_name=tool_name[:120],
                odoo_model=(odoo_model or None) and odoo_model[:120],
                odoo_method=(odoo_method or None) and odoo_method[:120],
                status=status[:20],
                duration_ms=max(0, int(duration_ms)),
                error=error[:1000] if error else None,
            ))
    except Exception as e:
        # Never let audit-log failures break a real request.
        log.warning("Failed to write audit row for %s: %s", tool_name, e)


def list_recent(
    *,
    limit: int = 100,
    since: datetime | None = None,
    user_id: int | None = None,
    tool_name: str | None = None,
    status: str | None = None,
) -> list[dict[str, Any]]:
    """Read recent audit rows as a list of plain dicts ready for JSON.

    Filters are AND-combined; pass `None`/omit to skip a filter. Results
    come back newest-first, capped at `limit` (max 1000 to keep payloads
    sane).
    """
    if not is_enabled():
        return []
    limit = max(1, min(int(limit), 1000))

    stmt = select(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit)
    if since is not None:
        stmt = stmt.where(AuditLog.created_at >= since)
    if user_id is not None:
        stmt = stmt.where(AuditLog.user_id == user_id)
    if tool_name:
        stmt = stmt.where(AuditLog.tool_name == tool_name)
    if status:
        stmt = stmt.where(AuditLog.status == status)

    with session_scope() as session:
        rows = list(session.scalars(stmt))
        return [
            {
                "id": r.id,
                "user_id": r.user_id,
                "tool_name": r.tool_name,
                "odoo_model": r.odoo_model,
                "odoo_method": r.odoo_method,
                "status": r.status,
                "duration_ms": r.duration_ms,
                "error": r.error,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]
