"""Thin XML-RPC wrapper around Odoo's external API.

Phase 1: preserves the exact behavior of the original `_connect` / `_x`
helpers from server.py v2.0. Phase 2 will replace this with an
`OdooClient` class that caches authenticated UIDs per session and
supports JSON-RPC + version detection.
"""

from __future__ import annotations

import xmlrpc.client
from datetime import date

from mezake_mcp.config import get_settings


def connect() -> tuple[int, xmlrpc.client.ServerProxy]:
    """Authenticate to Odoo and return (uid, object-proxy).

    Raises RuntimeError if authentication fails.
    """
    s = get_settings()
    common = xmlrpc.client.ServerProxy(f"{s.odoo_url}/xmlrpc/2/common")
    uid = common.authenticate(s.odoo_db, s.odoo_user, s.odoo_api_key, {})
    if not uid:
        raise RuntimeError("Odoo authentication failed. Check ODOO_USER and ODOO_API_KEY.")
    return uid, xmlrpc.client.ServerProxy(f"{s.odoo_url}/xmlrpc/2/object")


def _context() -> dict:
    s = get_settings()
    return {"allowed_company_ids": [s.odoo_company_id]} if s.odoo_company_id else {}


def execute(model: str, method: str, args: list, kw: dict | None = None):
    """Execute `model.method(*args, **kw)` on Odoo via XML-RPC.

    Automatically attaches `allowed_company_ids` context when
    ODOO_COMPANY_ID is set.
    """
    s = get_settings()
    uid, obj = connect()
    kw = kw or {}
    ctx = _context()
    if ctx:
        kw.setdefault("context", ctx)
    return obj.execute_kw(s.odoo_db, uid, s.odoo_api_key, model, method, args, kw)


def today() -> str:
    return date.today().isoformat()


# ── Legacy short aliases used by tools/legacy.py ──────────────────────────────
_x = execute
_connect = connect
_ctx = _context
_today = today
