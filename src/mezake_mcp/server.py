"""FastMCP server entry point.

Registers tools (via `mezake_mcp.tools`) and the OAuth routes (via
`mezake_mcp.auth.routes`) by side-effect import, then runs the
streamable-HTTP transport.

The OAuth endpoints themselves are real as of Phase 4b — PKCE-bound
authorization codes, access + refresh bearer tokens, persisted in
Postgres. The Bearer middleware that enforces tokens on /mcp lands
in Phase 4c; until then, /mcp still accepts any bearer so the
existing Claude.ai connector keeps working during the cut-over.
"""

from __future__ import annotations

import logging

from starlette.requests import Request
from starlette.responses import JSONResponse

from mezake_mcp import __version__
from mezake_mcp import tools  # noqa: F401 — side-effect import: registers tools
from mezake_mcp.auth import routes as _auth_routes  # noqa: F401 — registers auth routes
from mezake_mcp.config import get_settings
from mezake_mcp.logging_setup import configure_logging
from mezake_mcp.mcp_instance import mcp
from mezake_mcp.storage import db as storage_db
from mezake_mcp.storage import migrate as storage_migrate

log = logging.getLogger(__name__)


# ── Health ────────────────────────────────────────────────────────────────────

@mcp.custom_route("/health", methods=["GET"])
async def health(_: Request) -> JSONResponse:
    return JSONResponse({"status": "ok", "server": f"Odoo MCP v{__version__}"})


# ── Entry point ────────────────────────────────────────────────────────────────

def main() -> None:
    s = get_settings()
    configure_logging(s.log_level)
    log.info("Starting Odoo MCP v%s on %s (port %d)", __version__, s.base_url, s.port)

    # Storage is optional until Phase 4c lands; these calls are no-ops if
    # DATABASE_URL isn't set.
    storage_db.init()
    storage_migrate.upgrade_to_head()

    # Seed the default tenant+user+connection from env vars on first boot.
    from mezake_mcp.auth.bootstrap import bootstrap_default_user
    bootstrap_default_user()

    mcp.run(transport="streamable-http")
