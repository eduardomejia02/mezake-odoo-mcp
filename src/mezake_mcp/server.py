"""FastMCP server entry point.

Holds the OAuth custom routes required by Claude.ai's MCP handshake,
plus the `main()` function that starts the streamable-HTTP transport.

NOTE — the OAuth implementation here is cosmetic: it satisfies the
protocol shape Claude.ai expects but does not authenticate the caller.
Phase 4 of the rewrite replaces this with PKCE + Postgres-backed tokens
+ real Bearer validation. Until then, treat any deployed instance as
effectively public — do not point it at production Odoo data without
network-level restrictions.
"""

from __future__ import annotations

import logging
import secrets

from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse

from mezake_mcp import __version__
from mezake_mcp import tools  # noqa: F401 — side-effect import: registers tools
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


# ── OAuth (cosmetic; see module docstring) ────────────────────────────────────

@mcp.custom_route("/.well-known/oauth-protected-resource", methods=["GET"])
async def oauth_protected_resource(_: Request) -> JSONResponse:
    s = get_settings()
    return JSONResponse({
        "resource": s.base_url,
        "authorization_servers": [s.base_url],
        "bearer_methods_supported": ["header"],
        "scopes_supported": ["mcp"],
    })


@mcp.custom_route("/.well-known/oauth-authorization-server", methods=["GET"])
async def oauth_authorization_server(_: Request) -> JSONResponse:
    s = get_settings()
    return JSONResponse({
        "issuer": s.base_url,
        "authorization_endpoint": f"{s.base_url}/authorize",
        "token_endpoint": f"{s.base_url}/token",
        "registration_endpoint": f"{s.base_url}/register",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code"],
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": ["none"],
        "scopes_supported": ["mcp"],
    })


@mcp.custom_route("/register", methods=["POST"])
async def register(request: Request) -> JSONResponse:
    try:
        body = await request.json()
    except Exception:
        body = {}
    return JSONResponse({
        "client_id": f"mcp-client-{secrets.token_hex(8)}",
        "client_id_issued_at": 0,
        "redirect_uris": body.get("redirect_uris", []),
        "grant_types": ["authorization_code"],
        "response_types": ["code"],
        "client_name": body.get("client_name", "Claude"),
        "token_endpoint_auth_method": "none",
    }, status_code=201)


@mcp.custom_route("/authorize", methods=["GET"])
async def authorize(request: Request) -> RedirectResponse:
    redirect_uri = request.query_params.get("redirect_uri", "")
    state = request.query_params.get("state", "")
    code = secrets.token_urlsafe(32)
    sep = "&" if "?" in redirect_uri else "?"
    return RedirectResponse(url=f"{redirect_uri}{sep}code={code}&state={state}", status_code=302)


@mcp.custom_route("/token", methods=["POST"])
async def token(_: Request) -> JSONResponse:
    return JSONResponse({
        "access_token": secrets.token_urlsafe(32),
        "token_type": "bearer",
        "expires_in": 2592000,
        "scope": "mcp",
    })


# ── Entry point ────────────────────────────────────────────────────────────────

def main() -> None:
    s = get_settings()
    configure_logging(s.log_level)
    log.info("Starting Odoo MCP v%s on %s (port %d)", __version__, s.base_url, s.port)

    # Storage (Postgres) is optional — init() is a no-op if DATABASE_URL
    # isn't set, and migrate.upgrade_to_head() no-ops likewise. This keeps
    # the server bootable before the Railway Postgres plugin is attached.
    storage_db.init()
    storage_migrate.upgrade_to_head()

    # Phase 4a: seed default tenant+user+connection from env vars on first
    # boot. No-op if storage or ENCRYPTION_KEY isn't configured, or if the
    # `users` table already has rows.
    from mezake_mcp.auth.bootstrap import bootstrap_default_user
    bootstrap_default_user()

    mcp.run(transport="streamable-http")
