"""Request-scoped context for the authenticated user + their Odoo client.

The Bearer middleware resolves the bearer token, loads the user's
`OdooConnection`, builds (or retrieves a cached) `OdooClient`, and sets
these ContextVars for the duration of the request. Tool implementations
read them via `get_current_client()` — which falls through to the
env-var singleton when nothing is set (stdio transport, background
jobs, tests).
"""

from __future__ import annotations

from contextvars import ContextVar
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mezake_mcp.odoo.client import OdooClient


current_client: ContextVar["OdooClient | None"] = ContextVar(
    "mezake_current_client", default=None
)
current_user_id: ContextVar[int | None] = ContextVar(
    "mezake_current_user_id", default=None
)
