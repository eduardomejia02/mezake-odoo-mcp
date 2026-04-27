"""Audit log writes.

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
  - We never raise from here. Audit failures get logged at WARNING
    and the tool call still returns its result.
"""

from __future__ import annotations

import logging

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
