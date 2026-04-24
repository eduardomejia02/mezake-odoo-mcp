"""Tests for access + refresh token issuance, resolution, refresh, revoke."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select, update

from mezake_mcp.auth import tokens
from mezake_mcp.storage.db import session_scope
from mezake_mcp.storage.models import OAuthToken, Tenant, User


@pytest.fixture
def seeded_user(inmemory_db):
    with session_scope() as session:
        tenant = Tenant(name="Default", plan="self-hosted")
        session.add(tenant)
        session.flush()
        user = User(tenant_id=tenant.id, email="user@example.com")
        session.add(user)
        session.flush()
        yield user.id


class TestIssue:
    def test_returns_both_tokens(self, seeded_user) -> None:
        issued = tokens.issue(seeded_user)
        assert issued.access_token
        assert issued.refresh_token
        assert issued.access_token != issued.refresh_token
        assert issued.expires_in == tokens.ACCESS_TTL_SECONDS
        assert issued.scope == "mcp"

    def test_persists_both_as_hashes(self, seeded_user) -> None:
        issued = tokens.issue(seeded_user)
        with session_scope() as session:
            rows = list(session.scalars(select(OAuthToken)))
            kinds = {r.kind for r in rows}
            assert kinds == {"access", "refresh"}
            for r in rows:
                assert r.token_hash not in (issued.access_token, issued.refresh_token)


class TestResolveAccess:
    def test_happy_path(self, seeded_user) -> None:
        issued = tokens.issue(seeded_user)
        assert tokens.resolve_access(issued.access_token) == seeded_user

    def test_unknown_raises(self, seeded_user) -> None:
        with pytest.raises(tokens.TokenError, match="Unknown"):
            tokens.resolve_access("not-a-token")

    def test_refresh_token_rejected_as_access(self, seeded_user) -> None:
        issued = tokens.issue(seeded_user)
        with pytest.raises(tokens.TokenError, match="Expected access"):
            tokens.resolve_access(issued.refresh_token)

    def test_revoked_raises(self, seeded_user) -> None:
        issued = tokens.issue(seeded_user)
        tokens.revoke(issued.access_token)
        with pytest.raises(tokens.TokenError, match="revoked"):
            tokens.resolve_access(issued.access_token)

    def test_expired_raises(self, seeded_user) -> None:
        issued = tokens.issue(seeded_user)
        with session_scope() as session:
            session.execute(
                update(OAuthToken)
                .where(OAuthToken.kind == "access")
                .values(expires_at=datetime.now(timezone.utc) - timedelta(seconds=1))
            )
        with pytest.raises(tokens.TokenError, match="expired"):
            tokens.resolve_access(issued.access_token)


class TestRefresh:
    def test_refresh_issues_new_pair(self, seeded_user) -> None:
        old = tokens.issue(seeded_user)
        new = tokens.refresh(old.refresh_token)
        assert new.access_token != old.access_token
        assert new.refresh_token != old.refresh_token
        # New access token works
        assert tokens.resolve_access(new.access_token) == seeded_user

    def test_old_refresh_token_is_revoked(self, seeded_user) -> None:
        old = tokens.issue(seeded_user)
        tokens.refresh(old.refresh_token)
        with pytest.raises(tokens.TokenError, match="revoked"):
            tokens.refresh(old.refresh_token)

    def test_access_token_rejected_as_refresh(self, seeded_user) -> None:
        issued = tokens.issue(seeded_user)
        with pytest.raises(tokens.TokenError, match="Not a refresh"):
            tokens.refresh(issued.access_token)


class TestRevoke:
    def test_revoke_is_idempotent_and_silent_on_unknown(self, seeded_user) -> None:
        tokens.revoke("unknown")  # must not raise
        issued = tokens.issue(seeded_user)
        tokens.revoke(issued.access_token)
        tokens.revoke(issued.access_token)  # revoking twice is fine
