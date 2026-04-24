"""Postgres-backed persistence for tenants, users, OAuth, and audit log.

This module is optional at runtime: if `DATABASE_URL` is not set, the
server still boots and the legacy single-tenant flows continue to work.
Storage only becomes required once Phase 4 (real OAuth) lands.
"""

from mezake_mcp.storage.db import (
    get_engine,
    init,
    is_enabled,
    session_scope,
)
from mezake_mcp.storage.models import (
    AuditLog,
    Base,
    OAuthCode,
    OAuthToken,
    OdooConnection,
    Tenant,
    User,
)

__all__ = [
    "AuditLog",
    "Base",
    "OAuthCode",
    "OAuthToken",
    "OdooConnection",
    "Tenant",
    "User",
    "get_engine",
    "init",
    "is_enabled",
    "session_scope",
]
