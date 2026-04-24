"""Authorization-code issuance and single-use redemption.

Flow:
  1. User completes the /authorize onboarding form.
  2. `issue()` mints a one-time code, binds it to the PKCE
     `code_challenge` that Claude.ai sent in the original request, and
     persists only the SHA-256 hash.
  3. Claude.ai exchanges the raw code + its `code_verifier` at /token.
  4. `redeem()` validates PKCE, checks expiration, marks the code
     consumed, and returns the user_id.

Codes live 60 seconds — long enough for the redirect round-trip, short
enough to limit replay windows. They're single-use: a second /token
attempt with the same code is rejected.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update

from mezake_mcp.auth.pkce import verify as pkce_verify
from mezake_mcp.storage.db import session_scope
from mezake_mcp.storage.models import OAuthCode

CODE_TTL_SECONDS = 60


class CodeError(ValueError):
    """Raised when a code is unknown, expired, reused, or fails PKCE."""


def _hash(code: str) -> str:
    return hashlib.sha256(code.encode("ascii")).hexdigest()


def issue(
    user_id: int,
    client_id: str,
    redirect_uri: str,
    code_challenge: str,
    code_challenge_method: str = "S256",
) -> str:
    """Mint a fresh authorization code and return the raw (un-hashed) value."""
    raw = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=CODE_TTL_SECONDS)
    with session_scope() as session:
        session.add(
            OAuthCode(
                code_hash=_hash(raw),
                user_id=user_id,
                client_id=client_id,
                redirect_uri=redirect_uri,
                code_challenge=code_challenge,
                code_challenge_method=code_challenge_method,
                expires_at=expires_at,
            )
        )
    return raw


def redeem(code: str, code_verifier: str, redirect_uri: str) -> int:
    """Validate the code + PKCE + redirect_uri, mark it used, return user_id.

    Raises `CodeError` on any failure.
    """
    code_hash = _hash(code)
    now = datetime.now(timezone.utc)
    with session_scope() as session:
        row = session.scalar(select(OAuthCode).where(OAuthCode.code_hash == code_hash))
        if row is None:
            raise CodeError("Unknown authorization code")
        if row.used_at is not None:
            raise CodeError("Authorization code already used")
        # Compare timezone-aware dates. Some DB drivers (SQLite) return naive
        # datetimes for DateTime(timezone=True); coerce defensively.
        expires_at = row.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at < now:
            raise CodeError("Authorization code expired")
        if row.redirect_uri != redirect_uri:
            raise CodeError("redirect_uri mismatch")
        if not pkce_verify(code_verifier, row.code_challenge, row.code_challenge_method):
            raise CodeError("PKCE verification failed")
        user_id = row.user_id
        session.execute(
            update(OAuthCode)
            .where(OAuthCode.code_hash == code_hash)
            .values(used_at=now)
        )
    return user_id
