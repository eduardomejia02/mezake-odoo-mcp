"""Real OAuth 2.1 / PKCE route handlers.

These replace the cosmetic ones that previously lived in `server.py`:

  GET  /.well-known/oauth-protected-resource   — resource metadata
  GET  /.well-known/oauth-authorization-server — issuer metadata
  POST /register                                — dynamic client stub (stateless)
  GET  /authorize                               — renders onboarding form
  POST /authorize                               — validates creds, mints code, redirects
  POST /token                                   — code+PKCE or refresh -> (access, refresh)

Phase 4b ships these as the new authoritative endpoints. The /mcp route
itself still accepts any bearer — the Bearer middleware that enforces
real tokens lands in Phase 4c.
"""

from __future__ import annotations

import logging
import secrets

from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse

from mezake_mcp import audit
from mezake_mcp.auth import codes as auth_codes
from mezake_mcp.auth import onboarding, tokens
from mezake_mcp.auth.admin import is_current_user_admin
from mezake_mcp.auth.onboarding import (
    OnboardingError,
    OnboardingInput,
    find_or_create_user_and_connection,
    validate_odoo_credentials,
)
from mezake_mcp.config import get_settings
from mezake_mcp.mcp_instance import mcp
from mezake_mcp.storage.db import session_scope
from mezake_mcp.storage.models import Tenant, User

log = logging.getLogger(__name__)


# ── Discovery endpoints ───────────────────────────────────────────────────────

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
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": ["none"],
        "scopes_supported": ["mcp"],
    })


# ── Dynamic client registration (stateless stub) ──────────────────────────────
# Claude.ai POSTs client metadata here before /authorize. We don't persist it —
# the client_id we issue is a random string the caller will echo back. That's
# sufficient as long as downstream code doesn't trust client_id for auth
# decisions. (It doesn't: PKCE + the code binding protect the code exchange.)

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
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "client_name": body.get("client_name", "Claude"),
        "token_endpoint_auth_method": "none",
    }, status_code=201)


# ── /authorize ─────────────────────────────────────────────────────────────────

_REQUIRED_AUTHORIZE_PARAMS = (
    "client_id",
    "redirect_uri",
    "code_challenge",
)


def _authorize_params(source: dict) -> dict:
    """Pull the OAuth params out of a dict (query or form)."""
    return {
        "client_id": source.get("client_id", ""),
        "redirect_uri": source.get("redirect_uri", ""),
        "state": source.get("state", ""),
        "code_challenge": source.get("code_challenge", ""),
        "code_challenge_method": source.get("code_challenge_method", "S256"),
        "scope": source.get("scope", "mcp"),
    }


def _missing_param_response(params: dict) -> JSONResponse | None:
    missing = [k for k in _REQUIRED_AUTHORIZE_PARAMS if not params.get(k)]
    if missing:
        return JSONResponse(
            {"error": "invalid_request",
             "error_description": f"Missing required param(s): {', '.join(missing)}"},
            status_code=400,
        )
    if params["code_challenge_method"] != "S256":
        return JSONResponse(
            {"error": "invalid_request",
             "error_description": "Only code_challenge_method=S256 is supported"},
            status_code=400,
        )
    return None


@mcp.custom_route("/authorize", methods=["GET", "POST"])
async def authorize(request: Request):
    """GET renders the onboarding form; POST validates and redirects back."""
    if request.method == "GET":
        params = _authorize_params(dict(request.query_params))
        err = _missing_param_response(params)
        if err is not None:
            return err
        html = onboarding.render_form(**params)
        return HTMLResponse(html)

    # POST
    form = await request.form()
    params = _authorize_params(form)
    err = _missing_param_response(params)
    if err is not None:
        return err

    odoo_input = OnboardingInput(
        odoo_url=form.get("odoo_url", "").strip(),
        odoo_db=form.get("odoo_db", "").strip(),
        odoo_login=form.get("odoo_login", "").strip(),
        odoo_api_key=form.get("odoo_api_key", "").strip(),
    )
    if not all([odoo_input.odoo_url, odoo_input.odoo_db,
                odoo_input.odoo_login, odoo_input.odoo_api_key]):
        html = onboarding.render_form(
            **params,
            error="All fields are required.",
            odoo_url=odoo_input.odoo_url,
            odoo_db=odoo_input.odoo_db,
            odoo_login=odoo_input.odoo_login,
        )
        return HTMLResponse(html, status_code=400)

    try:
        validate_odoo_credentials(odoo_input)
    except OnboardingError as e:
        log.info("Onboarding credential validation failed: %s", e)
        html = onboarding.render_form(
            **params,
            error=str(e),
            odoo_url=odoo_input.odoo_url,
            odoo_db=odoo_input.odoo_db,
            odoo_login=odoo_input.odoo_login,
        )
        return HTMLResponse(html, status_code=400)

    user_id = find_or_create_user_and_connection(odoo_input)
    code = auth_codes.issue(
        user_id=user_id,
        client_id=params["client_id"],
        redirect_uri=params["redirect_uri"],
        code_challenge=params["code_challenge"],
        code_challenge_method=params["code_challenge_method"],
    )
    sep = "&" if "?" in params["redirect_uri"] else "?"
    redirect = f"{params['redirect_uri']}{sep}code={code}&state={params['state']}"
    log.info("Issued authorization code for user_id=%s", user_id)
    return RedirectResponse(url=redirect, status_code=302)


# ── /token ─────────────────────────────────────────────────────────────────────

@mcp.custom_route("/token", methods=["POST"])
async def token(request: Request) -> JSONResponse:
    """Authorization code exchange + refresh token grant."""
    form = await request.form()
    grant_type = form.get("grant_type", "")

    if grant_type == "authorization_code":
        code = form.get("code", "")
        code_verifier = form.get("code_verifier", "")
        redirect_uri = form.get("redirect_uri", "")
        if not (code and code_verifier and redirect_uri):
            return _token_error("invalid_request",
                                "code, code_verifier, and redirect_uri are required")
        try:
            user_id = auth_codes.redeem(code, code_verifier, redirect_uri)
        except auth_codes.CodeError as e:
            return _token_error("invalid_grant", str(e))
        issued = tokens.issue(user_id)
        return _token_response(issued)

    if grant_type == "refresh_token":
        refresh_token_str = form.get("refresh_token", "")
        if not refresh_token_str:
            return _token_error("invalid_request", "refresh_token is required")
        try:
            issued = tokens.refresh(refresh_token_str)
        except tokens.TokenError as e:
            return _token_error("invalid_grant", str(e))
        return _token_response(issued)

    return _token_error(
        "unsupported_grant_type",
        f"grant_type '{grant_type}' is not supported",
    )


def _token_response(issued: tokens.IssuedTokens) -> JSONResponse:
    return JSONResponse({
        "access_token": issued.access_token,
        "token_type": "bearer",
        "expires_in": issued.expires_in,
        "refresh_token": issued.refresh_token,
        "scope": issued.scope,
    })


def _token_error(code: str, description: str) -> JSONResponse:
    return JSONResponse({"error": code, "error_description": description}, status_code=400)


# ════════════════════════════════════════════════════════════════════════════
# /admin
# ════════════════════════════════════════════════════════════════════════════
# Gated by:
#   1. The Bearer middleware (authenticated user_id required) — same as /mcp
#   2. `is_current_user_admin()` — user's email must be in ADMIN_EMAILS env
#      var. Returns 403 otherwise.
#
# The first-pass surface is read-only (audit + tenants list). Mutating
# operations (plan changes, revocation, ban) come in Phase 7 alongside
# billing.

def _forbidden() -> JSONResponse:
    return JSONResponse({"error": "forbidden"}, status_code=403)


@mcp.custom_route("/admin/audit", methods=["GET"])
async def admin_audit(request: Request) -> JSONResponse:
    """Return recent audit events. Filters: ?since=ISO8601, ?user_id=N,
    ?tool=name, ?status=ok|error|denied, ?limit=N (max 1000)."""
    if not is_current_user_admin():
        return _forbidden()

    from datetime import datetime

    qp = request.query_params
    since_raw = qp.get("since")
    since: datetime | None = None
    if since_raw:
        try:
            since = datetime.fromisoformat(since_raw)
        except ValueError:
            return JSONResponse(
                {"error": "invalid_request",
                 "error_description": "since must be ISO 8601"},
                status_code=400,
            )

    user_id_raw = qp.get("user_id")
    user_id: int | None = None
    if user_id_raw:
        try:
            user_id = int(user_id_raw)
        except ValueError:
            return JSONResponse(
                {"error": "invalid_request", "error_description": "user_id must be int"},
                status_code=400,
            )

    rows = audit.list_recent(
        limit=int(qp.get("limit", 100) or 100),
        since=since,
        user_id=user_id,
        tool_name=qp.get("tool"),
        status=qp.get("status"),
    )
    return JSONResponse({"events": rows, "count": len(rows)})


@mcp.custom_route("/admin/tenants", methods=["GET"])
async def admin_tenants(_: Request) -> JSONResponse:
    """List tenants with user counts."""
    if not is_current_user_admin():
        return _forbidden()

    from sqlalchemy import func, select

    with session_scope() as session:
        rows = session.execute(
            select(
                Tenant.id, Tenant.name, Tenant.plan,
                Tenant.billing_customer_id, Tenant.created_at,
                func.count(User.id).label("user_count"),
            )
            .join(User, User.tenant_id == Tenant.id, isouter=True)
            .group_by(Tenant.id)
            .order_by(Tenant.id)
        ).all()
        tenants = [
            {
                "id": r.id,
                "name": r.name,
                "plan": r.plan,
                "billing_customer_id": r.billing_customer_id,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "user_count": r.user_count,
            }
            for r in rows
        ]
    return JSONResponse({"tenants": tenants, "count": len(tenants)})
