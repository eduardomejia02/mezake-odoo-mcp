"""Admin-role helpers.

A user is an admin iff their email is listed in `ADMIN_EMAILS`. This
keeps the admin role as a *deployment* concern, not a user-table column
— so granting/revoking admin doesn't require a DB write or a migration,
and it's impossible for someone to escalate themselves via the
onboarding flow alone.

The endpoints under `/admin/*` rely on this helper to return 403 when
the current authenticated user isn't admin.
"""

from __future__ import annotations

from sqlalchemy import select

from mezake_mcp.auth.context import current_user_id
from mezake_mcp.config import get_settings
from mezake_mcp.storage.db import is_enabled, session_scope
from mezake_mcp.storage.models import User


def is_admin_email(email: str) -> bool:
    """Check `email` against the configured `ADMIN_EMAILS` allow-list."""
    if not email:
        return False
    return email.strip().lower() in get_settings().admin_email_set


def is_current_user_admin() -> bool:
    """Return True iff the request's authenticated user is an admin.

    Reads the user_id from the Bearer middleware's contextvar, looks up
    the email, and checks the allow-list. False when no user is set
    (called outside an authenticated request) or storage is disabled.
    """
    user_id = current_user_id.get()
    if user_id is None or not is_enabled():
        return False
    with session_scope() as session:
        email = session.scalar(select(User.email).where(User.id == user_id))
    return bool(email) and is_admin_email(email)
