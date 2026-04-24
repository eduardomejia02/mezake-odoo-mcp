"""FastMCP server entry point.

Registers tools (via `mezake_mcp.tools`) and the OAuth routes (via
`mezake_mcp.auth.routes`) by side-effect import, wraps the FastMCP
Starlette app in `BearerAuthMiddleware`, and runs uvicorn directly.

Phase 4c is the cut-over: `/mcp` traffic is gated by real access
tokens issued by `/token`. `/authorize`, `/token`, `/.well-known/*`,
`/register`, and `/health` remain public by design.
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

    storage_db.init()
    storage_migrate.upgrade_to_head()

    # Seed the default tenant+user+connection from env vars on first boot.
    from mezake_mcp.auth.bootstrap import bootstrap_default_user
    bootstrap_default_user()

    # Build the Starlette app and attach the Bearer middleware *before*
    # handing off to uvicorn — Starlette freezes the middleware stack on
    # first request, so this must happen here, not inside mcp.run().
    import uvicorn

    from mezake_mcp.auth.middleware import BearerAuthMiddleware

    app = mcp.streamable_http_app()
    app.add_middleware(BearerAuthMiddleware)

    uvicorn.run(app, host="0.0.0.0", port=s.port, log_config=None)
