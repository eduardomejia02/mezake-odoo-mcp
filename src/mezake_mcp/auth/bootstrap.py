"""One-time bootstrap: seed the default tenant + user + Odoo connection
from environment variables on first startup.

Makes the Phase 1-3 → Phase 4 transition zero-friction: the operator's
own ODOO_URL / ODOO_DB / ODOO_USER / ODOO_API_KEY become the first user
automatically, so they can complete the OAuth handshake without
retyping their credentials.

Runs only when ALL of the following are true:
  - storage is enabled (DATABASE_URL is set)
  - ENCRYPTION_KEY is set (required to persist the API key)
  - the `users` table is empty (first-ever startup after Phase 3)
  - all four Odoo env vars are present

Idempotent: once a user exists, subsequent boots short-circuit.
"""

from __future__ import annotations

import logging

from sqlalchemy import func, select

from mezake_mcp.auth.crypto import encrypt
from mezake_mcp.config import get_settings
from mezake_mcp.storage import db
from mezake_mcp.storage.models import OdooConnection, Tenant, User

log = logging.getLogger(__name__)


def bootstrap_default_user() -> None:
    """Seed the first tenant + user + connection, if the preconditions hold."""
    if not db.is_enabled():
        return

    settings = get_settings()

    if not settings.encryption_key:
        log.warning(
            "ENCRYPTION_KEY not set; skipping bootstrap. "
            "Set ENCRYPTION_KEY in the environment to enable it."
        )
        return

    required = (
        settings.odoo_url,
        settings.odoo_db,
        settings.odoo_user,
        settings.odoo_api_key,
    )
    if not all(required):
        log.info("Odoo env vars incomplete; skipping bootstrap")
        return

    # Short-circuit if any user already exists.
    with db.session_scope() as session:
        user_count = session.scalar(select(func.count()).select_from(User))
        if user_count:
            return

        log.info("Bootstrapping default tenant + user from env vars")
        tenant = Tenant(name="Default", plan="self-hosted")
        session.add(tenant)
        session.flush()

        user = User(tenant_id=tenant.id, email=settings.odoo_user)
        session.add(user)
        session.flush()

        connection = OdooConnection(
            user_id=user.id,
            url=settings.odoo_url,
            db=settings.odoo_db,
            login=settings.odoo_user,
            api_key_encrypted=encrypt(settings.odoo_api_key),
        )
        session.add(connection)

    log.info("Bootstrap complete — default tenant + user seeded")
