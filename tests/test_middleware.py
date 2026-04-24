"""Tests for BearerAuthMiddleware.

Exercises the ASGI contract directly with a stub inner app so we can
assert what path the middleware took without spinning up uvicorn.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from mezake_mcp.auth import tokens
from mezake_mcp.auth.context import current_client, current_user_id
from mezake_mcp.auth.crypto import encrypt
from mezake_mcp.auth.middleware import BearerAuthMiddleware
from mezake_mcp.auth.resolver import reset_cache
from mezake_mcp.storage.db import session_scope
from mezake_mcp.storage.models import OdooConnection, Tenant, User


class _Recorder:
    """A stub ASGI app that records whether it was called and under what context."""

    def __init__(self):
        self.called = False
        self.seen_user_id: int | None = None
        self.seen_client_url: str | None = None

    async def __call__(self, scope, receive, send):
        self.called = True
        self.seen_user_id = current_user_id.get()
        client = current_client.get()
        self.seen_client_url = client._url if client is not None else None
        await send({
            "type": "http.response.start",
            "status": 200,
            "headers": [(b"content-type", b"text/plain")],
        })
        await send({"type": "http.response.body", "body": b"ok"})


class _SendCapture:
    def __init__(self):
        self.messages: list[dict] = []

    async def __call__(self, message):
        self.messages.append(message)

    @property
    def status(self) -> int:
        for m in self.messages:
            if m["type"] == "http.response.start":
                return m["status"]
        raise AssertionError("No start message captured")

    @property
    def header_map(self) -> dict[str, str]:
        for m in self.messages:
            if m["type"] == "http.response.start":
                return {k.decode().lower(): v.decode() for k, v in m["headers"]}
        raise AssertionError("No start message captured")


def _scope(path: str, headers: list[tuple[bytes, bytes]] | None = None) -> dict:
    return {
        "type": "http",
        "path": path,
        "method": "POST",
        "headers": headers or [],
    }


async def _noop_receive():
    return {"type": "http.request", "body": b"", "more_body": False}


@pytest.fixture
def seeded_user_with_connection(inmemory_db, encryption_key):
    reset_cache()
    with session_scope() as session:
        tenant = Tenant(name="Default", plan="self-hosted")
        session.add(tenant)
        session.flush()
        user = User(tenant_id=tenant.id, email="user@example.com")
        session.add(user)
        session.flush()
        session.add(OdooConnection(
            user_id=user.id,
            url="https://example.odoo.com",
            db="example-db",
            login="user@example.com",
            api_key_encrypted=encrypt("raw-key"),
        ))
        uid = user.id
    yield uid
    reset_cache()


class TestNonProtectedPaths:
    async def test_health_passes_through_without_auth(self, inmemory_db) -> None:
        inner = _Recorder()
        mw = BearerAuthMiddleware(inner)
        send = _SendCapture()
        await mw(_scope("/health"), _noop_receive, send)
        assert inner.called
        assert inner.seen_user_id is None

    async def test_authorize_passes_through(self, inmemory_db) -> None:
        inner = _Recorder()
        mw = BearerAuthMiddleware(inner)
        send = _SendCapture()
        await mw(_scope("/authorize"), _noop_receive, send)
        assert inner.called

    async def test_token_passes_through(self, inmemory_db) -> None:
        inner = _Recorder()
        mw = BearerAuthMiddleware(inner)
        send = _SendCapture()
        await mw(_scope("/token"), _noop_receive, send)
        assert inner.called


class TestProtectedPaths:
    async def test_mcp_without_header_returns_401(self, inmemory_db) -> None:
        inner = _Recorder()
        mw = BearerAuthMiddleware(inner)
        send = _SendCapture()
        await mw(_scope("/mcp"), _noop_receive, send)
        assert not inner.called
        assert send.status == 401
        assert "bearer" in send.header_map["www-authenticate"].lower()

    async def test_mcp_with_malformed_header_returns_401(self, inmemory_db) -> None:
        inner = _Recorder()
        mw = BearerAuthMiddleware(inner)
        send = _SendCapture()
        await mw(
            _scope("/mcp", [(b"authorization", b"Basic abc")]),
            _noop_receive, send,
        )
        assert send.status == 401

    async def test_mcp_with_unknown_bearer_returns_401(self, inmemory_db) -> None:
        inner = _Recorder()
        mw = BearerAuthMiddleware(inner)
        send = _SendCapture()
        await mw(
            _scope("/mcp", [(b"authorization", b"Bearer nope")]),
            _noop_receive, send,
        )
        assert send.status == 401

    async def test_mcp_with_valid_bearer_sets_context_and_passes_through(
        self, seeded_user_with_connection
    ) -> None:
        issued = tokens.issue(seeded_user_with_connection)
        inner = _Recorder()
        mw = BearerAuthMiddleware(inner)
        send = _SendCapture()
        headers = [(b"authorization", f"Bearer {issued.access_token}".encode())]
        await mw(_scope("/mcp", headers), _noop_receive, send)
        assert inner.called
        assert inner.seen_user_id == seeded_user_with_connection
        assert inner.seen_client_url == "https://example.odoo.com"
        assert send.status == 200

    async def test_mcp_subpaths_are_gated(self, seeded_user_with_connection) -> None:
        inner = _Recorder()
        mw = BearerAuthMiddleware(inner)
        send = _SendCapture()
        await mw(_scope("/mcp/something"), _noop_receive, send)
        assert send.status == 401

    async def test_context_is_reset_after_request(
        self, seeded_user_with_connection
    ) -> None:
        issued = tokens.issue(seeded_user_with_connection)
        inner = _Recorder()
        mw = BearerAuthMiddleware(inner)
        send = _SendCapture()
        headers = [(b"authorization", f"Bearer {issued.access_token}".encode())]
        await mw(_scope("/mcp", headers), _noop_receive, send)
        # After the call returns, the contextvars should be back to their
        # default None values — not leaked to the next request.
        assert current_user_id.get() is None
        assert current_client.get() is None


class TestLifespan:
    async def test_non_http_scope_passes_through_unchanged(self, inmemory_db) -> None:
        inner = _Recorder()
        mw = BearerAuthMiddleware(inner)
        send = _SendCapture()
        await mw({"type": "lifespan"}, _noop_receive, send)
        assert inner.called
