"""Resolve a user_id to an `OdooClient` with their decrypted credentials.

Called by the Bearer middleware on each authenticated request. Clients
are cached by user_id — that cache is what gives us the fast path: the
first request after a cold start decrypts the API key and authenticates
to Odoo; subsequent requests reuse the same `OdooClient` (which itself
caches its uid + server version).

Cache invalidation:
  - On API-key rotation (user re-runs the /authorize flow), the
    onboarding step updates the row in-place and calls
    `invalidate_user(user_id)`, so the next request rebuilds the client.
  - On process restart, the cache is lost; that's fine.
"""

from __future__ import annotations

import threading

from sqlalchemy import select

from mezake_mcp.auth.crypto import decrypt
from mezake_mcp.odoo.client import OdooClient
from mezake_mcp.storage.db import session_scope
from mezake_mcp.storage.models import OdooConnection


class NoConnectionError(LookupError):
    """Raised when an authenticated user has no OdooConnection row."""


_cache: dict[int, OdooClient] = {}
_cache_lock = threading.Lock()


def load_client_for_user(user_id: int) -> OdooClient:
    """Return the cached `OdooClient` for `user_id`, building it if needed."""
    cached = _cache.get(user_id)
    if cached is not None:
        return cached
    with _cache_lock:
        cached = _cache.get(user_id)
        if cached is not None:
            return cached
        with session_scope() as session:
            conn = session.scalar(
                select(OdooConnection).where(OdooConnection.user_id == user_id)
            )
            if conn is None:
                raise NoConnectionError(f"No Odoo connection for user {user_id}")
            api_key = decrypt(conn.api_key_encrypted)
            client = OdooClient(
                url=conn.url,
                db=conn.db,
                login=conn.login,
                api_key=api_key,
            )
        _cache[user_id] = client
        return client


def invalidate_user(user_id: int) -> None:
    """Drop the cached client for `user_id`. Call after credential changes."""
    with _cache_lock:
        _cache.pop(user_id, None)


def reset_cache() -> None:
    """Clear the entire cache. For tests only."""
    with _cache_lock:
        _cache.clear()
