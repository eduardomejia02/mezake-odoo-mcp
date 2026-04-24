"""Access + refresh bearer tokens.

Raw tokens are returned to the client exactly once. Only SHA-256 hashes
are stored, so a DB dump is useless for impersonation and revocation
works by updating a `revoked_at` timestamp.

TTLs:
  access  = 1 hour    (short-lived; refresh to extend)
  refresh = 30 days   (matches the expectation Claude.ai sets)

Refreshing rotates both tokens: the old refresh token is revoked in the
same transaction that mints the new pair, so a leaked refresh token is
useful for at most one subsequent exchange.
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update

from mezake_mcp.storage.db import is_enabled, session_scope
from mezake_mcp.storage.models import OAuthToken

ACCESS_TTL_SECONDS = 3600
REFRESH_TTL_SECONDS = 30 * 24 * 3600


class TokenError(ValueError):
    """Raised when a token is unknown, revoked, expired, or the wrong kind."""


@dataclass(frozen=True)
class IssuedTokens:
    access_token: str
    refresh_token: str
    expires_in: int
    scope: str


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def _aware(dt: datetime) -> datetime:
    """Coerce a possibly-naive DB datetime to timezone-aware UTC."""
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def issue(user_id: int, scope: str = "mcp") -> IssuedTokens:
    """Mint a new (access, refresh) pair for `user_id`."""
    access_raw = secrets.token_urlsafe(32)
    refresh_raw = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)
    with session_scope() as session:
        session.add(
            OAuthToken(
                token_hash=_hash(access_raw),
                user_id=user_id,
                kind="access",
                scope=scope,
                expires_at=now + timedelta(seconds=ACCESS_TTL_SECONDS),
            )
        )
        session.add(
            OAuthToken(
                token_hash=_hash(refresh_raw),
                user_id=user_id,
                kind="refresh",
                scope=scope,
                expires_at=now + timedelta(seconds=REFRESH_TTL_SECONDS),
            )
        )
    return IssuedTokens(
        access_token=access_raw,
        refresh_token=refresh_raw,
        expires_in=ACCESS_TTL_SECONDS,
        scope=scope,
    )


def resolve_access(token: str) -> int:
    """Validate an access token and return its user_id. Raises `TokenError`."""
    if not is_enabled():
        raise TokenError("Authentication storage not available")
    token_hash = _hash(token)
    now = datetime.now(timezone.utc)
    with session_scope() as session:
        row = session.scalar(select(OAuthToken).where(OAuthToken.token_hash == token_hash))
        if row is None:
            raise TokenError("Unknown token")
        if row.kind != "access":
            raise TokenError(f"Expected access token, got {row.kind}")
        if row.revoked_at is not None:
            raise TokenError("Token revoked")
        if _aware(row.expires_at) < now:
            raise TokenError("Token expired")
        return row.user_id


def refresh(refresh_token: str) -> IssuedTokens:
    """Exchange a refresh token for a new (access, refresh) pair.
    Revokes the old refresh token atomically.
    """
    if not is_enabled():
        raise TokenError("Authentication storage not available")
    token_hash = _hash(refresh_token)
    now = datetime.now(timezone.utc)
    with session_scope() as session:
        row = session.scalar(select(OAuthToken).where(OAuthToken.token_hash == token_hash))
        if row is None:
            raise TokenError("Unknown refresh token")
        if row.kind != "refresh":
            raise TokenError("Not a refresh token")
        if row.revoked_at is not None:
            raise TokenError("Refresh token revoked")
        if _aware(row.expires_at) < now:
            raise TokenError("Refresh token expired")
        user_id = row.user_id
        scope = row.scope
        session.execute(
            update(OAuthToken)
            .where(OAuthToken.token_hash == token_hash)
            .values(revoked_at=now)
        )
    return issue(user_id, scope)


def revoke(token: str) -> None:
    """Mark a token as revoked. Silently ignores unknown tokens."""
    token_hash = _hash(token)
    with session_scope() as session:
        session.execute(
            update(OAuthToken)
            .where(OAuthToken.token_hash == token_hash)
            .values(revoked_at=datetime.now(timezone.utc))
        )
