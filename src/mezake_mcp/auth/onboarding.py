"""Onboarding: HTML form + Odoo credential validation + find-or-create user.

The /authorize route hands off here when the user submits the form. We:
  1. Validate the Odoo credentials by calling `common.authenticate`
     against the provided URL — if Odoo accepts them, they're valid.
  2. Find or create a User by email and an OdooConnection for that user.
     If a connection already exists, we update url/db/login/api_key in
     place — this is how a user rotates their API key or moves Odoo
     instances.
  3. Return the user_id so the caller can mint an auth code.

Everything here is synchronous; the Odoo validation blocks the request
thread. That's fine — the volume is one call per OAuth hand-off.
"""

from __future__ import annotations

import logging
import xmlrpc.client
from dataclasses import dataclass

from sqlalchemy import select

from mezake_mcp.auth.crypto import encrypt
from mezake_mcp.storage.db import session_scope
from mezake_mcp.storage.models import OdooConnection, Tenant, User

log = logging.getLogger(__name__)


class OnboardingError(ValueError):
    """Raised when the form data is invalid or Odoo rejects the credentials."""


@dataclass(frozen=True)
class OnboardingInput:
    odoo_url: str
    odoo_db: str
    odoo_login: str
    odoo_api_key: str

    def normalized_url(self) -> str:
        url = self.odoo_url.strip().rstrip("/")
        if not (url.startswith("http://") or url.startswith("https://")):
            url = "https://" + url
        return url


def validate_odoo_credentials(data: OnboardingInput) -> int:
    """Call `common.authenticate` on the target Odoo and return the uid.

    Raises OnboardingError on any failure (network, wrong db, bad key, …).
    """
    try:
        common = xmlrpc.client.ServerProxy(f"{data.normalized_url()}/xmlrpc/2/common")
        uid = common.authenticate(
            data.odoo_db, data.odoo_login, data.odoo_api_key, {}
        )
    except (xmlrpc.client.Fault, xmlrpc.client.ProtocolError, OSError) as e:
        raise OnboardingError(f"Could not reach Odoo at {data.odoo_url}: {e}") from e
    if not uid:
        raise OnboardingError(
            "Odoo rejected these credentials. "
            "Double-check the database name, login, and API key."
        )
    return int(uid)


def find_or_create_user_and_connection(data: OnboardingInput) -> int:
    """Persist the user + connection, returning the user_id.

    Contract:
      - One user per email globally (we're single-tenant for now).
      - One connection per user: the existing row is updated in place on
        re-auth rather than creating a duplicate. Future phases may relax
        this if users need multiple Odoo instances bound to one identity.
    """
    url = data.normalized_url()
    with session_scope() as session:
        user = session.scalar(select(User).where(User.email == data.odoo_login))
        if user is None:
            tenant = session.scalar(select(Tenant).limit(1))
            if tenant is None:
                tenant = Tenant(name="Default", plan="self-hosted")
                session.add(tenant)
                session.flush()
            user = User(tenant_id=tenant.id, email=data.odoo_login)
            session.add(user)
            session.flush()

        connection = session.scalar(
            select(OdooConnection).where(OdooConnection.user_id == user.id)
        )
        encrypted_key = encrypt(data.odoo_api_key)
        if connection is None:
            connection = OdooConnection(
                user_id=user.id,
                url=url,
                db=data.odoo_db,
                login=data.odoo_login,
                api_key_encrypted=encrypted_key,
            )
            session.add(connection)
        else:
            connection.url = url
            connection.db = data.odoo_db
            connection.login = data.odoo_login
            connection.api_key_encrypted = encrypted_key

        return user.id


# ── Minimal HTML form ─────────────────────────────────────────────────────────
# Kept inline (no templates, no static files) to avoid adding a templating
# dependency or a second process for static assets. Not designed to win
# awards — it just needs to collect four strings.

FORM_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Connect Odoo</title>
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <style>
    * {{ box-sizing: border-box; }}
    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
      background: #0f1115;
      color: #e6e6e6;
      margin: 0; padding: 40px 20px;
      display: flex; justify-content: center;
    }}
    .card {{
      background: #1a1d24;
      border: 1px solid #272b34;
      border-radius: 10px;
      padding: 32px;
      max-width: 460px;
      width: 100%;
    }}
    h1 {{ margin: 0 0 8px; font-size: 22px; font-weight: 600; }}
    p.sub {{ color: #9aa0ab; margin: 0 0 24px; font-size: 14px; line-height: 1.5; }}
    label {{ display: block; margin-top: 16px; font-size: 13px; color: #b8bec9; }}
    input {{
      width: 100%; padding: 10px 12px; margin-top: 6px;
      border: 1px solid #2e333e; background: #0f1115; color: #e6e6e6;
      border-radius: 6px; font-size: 14px;
    }}
    input:focus {{ outline: none; border-color: #6366f1; }}
    button {{
      width: 100%; margin-top: 24px; padding: 12px; font-size: 14px;
      background: #6366f1; color: white; border: 0; border-radius: 6px;
      cursor: pointer; font-weight: 600;
    }}
    button:hover {{ background: #4f46e5; }}
    .error {{
      margin: 16px 0 0; padding: 12px;
      background: #2d1b1f; border: 1px solid #4a2a30; border-radius: 6px;
      color: #fca5a5; font-size: 13px;
    }}
    .hint {{ font-size: 12px; color: #6b7280; margin-top: 4px; }}
  </style>
</head>
<body>
  <form class="card" method="post" action="/authorize">
    <h1>Connect Odoo to Claude</h1>
    <p class="sub">Enter your Odoo instance details. Credentials are encrypted at rest and used only to execute the actions you ask Claude to perform.</p>

    {error_html}

    <label>Odoo URL
      <input type="url" name="odoo_url" value="{odoo_url}" placeholder="https://yourcompany.odoo.com" required>
    </label>

    <label>Database name
      <input type="text" name="odoo_db" value="{odoo_db}" placeholder="company-production-xxxxx" required>
      <div class="hint">Visible in the URL after login, or under Settings → Technical.</div>
    </label>

    <label>Login email
      <input type="email" name="odoo_login" value="{odoo_login}" required>
    </label>

    <label>API key
      <input type="password" name="odoo_api_key" value="" required>
      <div class="hint">Settings → Users → your user → Account Security → New API Key.</div>
    </label>

    {hidden_fields}

    <button type="submit">Continue</button>
  </form>
</body>
</html>
"""


def render_form(
    *,
    client_id: str,
    redirect_uri: str,
    state: str,
    code_challenge: str,
    code_challenge_method: str,
    scope: str,
    error: str = "",
    odoo_url: str = "",
    odoo_db: str = "",
    odoo_login: str = "",
) -> str:
    """Render the onboarding form with OAuth params preserved as hidden inputs."""
    from html import escape

    hidden = "\n".join(
        f'<input type="hidden" name="{name}" value="{escape(value)}">'
        for name, value in [
            ("client_id", client_id),
            ("redirect_uri", redirect_uri),
            ("state", state),
            ("code_challenge", code_challenge),
            ("code_challenge_method", code_challenge_method),
            ("scope", scope),
        ]
    )
    error_html = f'<div class="error">{escape(error)}</div>' if error else ""
    return FORM_HTML.format(
        error_html=error_html,
        hidden_fields=hidden,
        odoo_url=escape(odoo_url),
        odoo_db=escape(odoo_db),
        odoo_login=escape(odoo_login),
    )
