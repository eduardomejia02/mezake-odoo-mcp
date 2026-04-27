"""Bearer authentication middleware for the `/mcp` endpoint.

Implements RFC 6750 Bearer Token validation as an ASGI middleware so it
runs outside Starlette's routing — this gives us a clean cut-off between
the public OAuth endpoints (`/authorize`, `/token`, `/.well-known/*`,
`/register`, `/health`) and the protected MCP endpoint.

Contract:
  - Any request to a path under the protected prefix must carry an
    `Authorization: Bearer <token>` header.
  - The token must resolve to a live (non-revoked, non-expired) access
    token. Invalid token -> 401 with `WWW-Authenticate: Bearer` header.
  - The user must have an `OdooConnection` row. If not -> 401.
  - On success, `current_client` and `current_user_id` ContextVars are
    set for the lifetime of the request and the call is delegated.
  - Non-HTTP ASGI events (lifespan, websocket, …) pass through unchanged.
"""

from __future__ import annotations

import logging

from mezake_mcp.auth import tokens
from mezake_mcp.auth.context import current_client, current_user_id
from mezake_mcp.auth.rate_limit import consume_one
from mezake_mcp.auth.resolver import NoConnectionError, load_client_for_user

log = logging.getLogger(__name__)


PROTECTED_PREFIXES = ("/mcp",)


class BearerAuthMiddleware:
    """ASGI middleware that enforces Bearer tokens on PROTECTED_PREFIXES."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path: str = scope.get("path", "")
        if not any(path == p or path.startswith(p + "/") or path == p for p in PROTECTED_PREFIXES):
            await self.app(scope, receive, send)
            return

        headers = {
            k.decode("latin-1").lower(): v.decode("latin-1")
            for k, v in scope.get("headers", [])
        }
        auth_header = headers.get("authorization", "")

        if not auth_header.lower().startswith("bearer "):
            await _send_401(send, "Missing or malformed Authorization header")
            return

        token = auth_header[7:].strip()
        try:
            user_id = tokens.resolve_access(token)
        except tokens.TokenError as e:
            log.info("Bearer rejected: %s", e)
            await _send_401(send, str(e))
            return

        try:
            client = load_client_for_user(user_id)
        except NoConnectionError as e:
            log.warning("Authenticated user %s has no Odoo connection", user_id)
            await _send_401(send, str(e))
            return

        # Rate limit AFTER successful auth so unauthenticated traffic
        # can't exhaust someone else's bucket and so 429 carries a
        # meaningful per-user accounting.
        allowed, retry_after = consume_one(user_id)
        if not allowed:
            log.info("Rate limit hit for user %s (retry after %.1fs)", user_id, retry_after)
            await _send_429(send, retry_after)
            return

        token_client = current_client.set(client)
        token_uid = current_user_id.set(user_id)
        try:
            await self.app(scope, receive, send)
        finally:
            current_client.reset(token_client)
            current_user_id.reset(token_uid)


async def _send_401(send, reason: str = "Unauthorized") -> None:
    body = f'{{"error":"unauthorized","error_description":"{reason}"}}'.encode()
    await send({
        "type": "http.response.start",
        "status": 401,
        "headers": [
            (b"content-type", b"application/json"),
            (b"www-authenticate", b'Bearer realm="mcp"'),
            (b"content-length", str(len(body)).encode()),
        ],
    })
    await send({"type": "http.response.body", "body": body})


async def _send_429(send, retry_after: float) -> None:
    body = b'{"error":"rate_limited","error_description":"Too many requests."}'
    # Cap the Retry-After header at 60s — `inf` (no-refill bucket) and
    # very large values aren't useful to send to a client.
    retry_after_secs = 60 if retry_after == float("inf") else max(1, int(retry_after) + 1)
    await send({
        "type": "http.response.start",
        "status": 429,
        "headers": [
            (b"content-type", b"application/json"),
            (b"retry-after", str(retry_after_secs).encode()),
            (b"content-length", str(len(body)).encode()),
        ],
    })
    await send({"type": "http.response.body", "body": body})
