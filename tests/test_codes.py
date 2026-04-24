"""Tests for authorization-code issuance + redemption.

Needs a DB (via the `inmemory_db` fixture) but no live Odoo.
"""

from __future__ import annotations

import base64
import hashlib
import time
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select, update

from mezake_mcp.auth import codes
from mezake_mcp.storage.db import session_scope
from mezake_mcp.storage.models import OAuthCode, Tenant, User


def _challenge_for(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


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
    def test_returns_urlsafe_string(self, seeded_user) -> None:
        code = codes.issue(
            user_id=seeded_user,
            client_id="client-1",
            redirect_uri="https://claude.ai/cb",
            code_challenge=_challenge_for("x" * 64),
        )
        assert isinstance(code, str) and len(code) > 20

    def test_persists_hash_not_plaintext(self, seeded_user) -> None:
        code = codes.issue(
            user_id=seeded_user,
            client_id="c",
            redirect_uri="https://claude.ai/cb",
            code_challenge=_challenge_for("y" * 64),
        )
        with session_scope() as session:
            row = session.scalar(select(OAuthCode))
            assert row.code_hash != code
            assert len(row.code_hash) == 64  # sha256 hex


class TestRedeem:
    def test_happy_path(self, seeded_user) -> None:
        verifier = "v" * 64
        code = codes.issue(
            user_id=seeded_user,
            client_id="c",
            redirect_uri="https://claude.ai/cb",
            code_challenge=_challenge_for(verifier),
        )
        user_id = codes.redeem(code, verifier, "https://claude.ai/cb")
        assert user_id == seeded_user

    def test_unknown_code_raises(self, seeded_user) -> None:
        with pytest.raises(codes.CodeError, match="Unknown"):
            codes.redeem("nope", "v" * 64, "https://claude.ai/cb")

    def test_second_use_raises(self, seeded_user) -> None:
        verifier = "v" * 64
        code = codes.issue(
            user_id=seeded_user,
            client_id="c",
            redirect_uri="https://claude.ai/cb",
            code_challenge=_challenge_for(verifier),
        )
        codes.redeem(code, verifier, "https://claude.ai/cb")
        with pytest.raises(codes.CodeError, match="already used"):
            codes.redeem(code, verifier, "https://claude.ai/cb")

    def test_wrong_verifier_raises(self, seeded_user) -> None:
        code = codes.issue(
            user_id=seeded_user,
            client_id="c",
            redirect_uri="https://claude.ai/cb",
            code_challenge=_challenge_for("v" * 64),
        )
        with pytest.raises(codes.CodeError, match="PKCE"):
            codes.redeem(code, "w" * 64, "https://claude.ai/cb")

    def test_redirect_uri_mismatch_raises(self, seeded_user) -> None:
        verifier = "v" * 64
        code = codes.issue(
            user_id=seeded_user,
            client_id="c",
            redirect_uri="https://claude.ai/cb",
            code_challenge=_challenge_for(verifier),
        )
        with pytest.raises(codes.CodeError, match="redirect_uri"):
            codes.redeem(code, verifier, "https://evil.example.com/cb")

    def test_expired_code_raises(self, seeded_user) -> None:
        verifier = "v" * 64
        code = codes.issue(
            user_id=seeded_user,
            client_id="c",
            redirect_uri="https://claude.ai/cb",
            code_challenge=_challenge_for(verifier),
        )
        # Force-expire by rewriting the expires_at column
        with session_scope() as session:
            session.execute(
                update(OAuthCode).values(
                    expires_at=datetime.now(timezone.utc) - timedelta(seconds=1)
                )
            )
        with pytest.raises(codes.CodeError, match="expired"):
            codes.redeem(code, verifier, "https://claude.ai/cb")
