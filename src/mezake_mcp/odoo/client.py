"""Odoo external-API client.

Wraps XML-RPC with:
  - Lazy authentication; the authenticated user ID is cached on the
    client and reused across every subsequent call.
  - Lazy version probing via `common.version()`, also cached.
  - Automatic re-auth on a single XML-RPC fault that looks like a
    session/UID invalidation, so API-key rotation doesn't take the
    process down.
  - A `stockable_domain()` / `sellable_product_domain()` pair that
    delegates to `compat` so tools stay version-agnostic.

The process holds ONE `OdooClient` for now, built from env settings by
`get_client()`. When Phase 4 introduces per-session credentials, each
OAuth session will own its own client with the same class — no
downstream tool changes needed.
"""

from __future__ import annotations

import logging
import threading
import xmlrpc.client
from datetime import date
from typing import Any

from mezake_mcp.config import get_settings
from mezake_mcp.odoo.compat import (
    VersionInfo,
    sellable_product_domain,
    stockable_product_domain,
)

log = logging.getLogger(__name__)


class OdooError(Exception):
    """Raised when Odoo rejects a request (auth failure, XML-RPC fault, …)."""


class OdooClient:
    """Thin Odoo external-API client with cached authentication.

    One instance represents one (url, db, login, api_key) credential
    set. Safe to share across threads — `execute_kw` takes a per-call
    lock only around the rare re-auth path; normal calls proceed in
    parallel through the XML-RPC `ServerProxy`, which is itself
    thread-safe for separate requests.
    """

    def __init__(
        self,
        url: str,
        db: str,
        login: str,
        api_key: str,
        company_id: int | None = None,
    ):
        self._url = url.rstrip("/")
        self._db = db
        self._login = login
        self._api_key = api_key
        self._company_id = company_id

        self._auth_lock = threading.Lock()
        self._uid: int | None = None
        self._version: VersionInfo | None = None
        self._common: xmlrpc.client.ServerProxy | None = None
        self._object: xmlrpc.client.ServerProxy | None = None

    # ── Connection primitives ─────────────────────────────────────────────────

    def _common_proxy(self) -> xmlrpc.client.ServerProxy:
        if self._common is None:
            self._common = xmlrpc.client.ServerProxy(f"{self._url}/xmlrpc/2/common")
        return self._common

    def _object_proxy(self) -> xmlrpc.client.ServerProxy:
        if self._object is None:
            self._object = xmlrpc.client.ServerProxy(f"{self._url}/xmlrpc/2/object")
        return self._object

    def _authenticate(self) -> int:
        """Authenticate once and cache the uid. Idempotent under lock."""
        with self._auth_lock:
            if self._uid is not None:
                return self._uid
            uid = self._common_proxy().authenticate(self._db, self._login, self._api_key, {})
            if not uid:
                raise OdooError(
                    "Odoo authentication failed. Check ODOO_USER and ODOO_API_KEY."
                )
            self._uid = int(uid)
            log.info("Odoo auth OK — uid=%s at %s db=%s", self._uid, self._url, self._db)
            return self._uid

    def _invalidate_auth(self) -> None:
        with self._auth_lock:
            self._uid = None

    # ── Public surface ────────────────────────────────────────────────────────

    @property
    def uid(self) -> int:
        """The authenticated user ID. Triggers auth on first access."""
        return self._uid if self._uid is not None else self._authenticate()

    @property
    def version(self) -> VersionInfo:
        """Odoo server version. Probed once via `common.version()` and cached."""
        if self._version is None:
            raw = self._common_proxy().version()
            self._version = VersionInfo.from_odoo(raw)
            log.info(
                "Odoo server version %s (%s) at %s",
                self._version.series,
                "Enterprise" if self._version.is_enterprise else "Community",
                self._url,
            )
        return self._version

    def context(self) -> dict:
        """Call context injected into every `execute_kw` — currently just
        `allowed_company_ids` if the deploy is locked to one company."""
        return {"allowed_company_ids": [self._company_id]} if self._company_id else {}

    def execute_kw(
        self,
        model: str,
        method: str,
        args: list,
        kw: dict | None = None,
    ) -> Any:
        """Run `model.method(*args, **kw)` via XML-RPC.

        Automatically attaches the company context. If the caller passes
        their own `context` (e.g. `{"lang": "en_US"}` for translations),
        it's MERGED with the company context — caller wins on conflicts,
        but `allowed_company_ids` is preserved unless the caller
        explicitly overrides it.

        Retries exactly once on UID rejection (e.g. after an API-key rotation).
        """
        kw = dict(kw) if kw else {}
        deployment_ctx = self.context()
        caller_ctx = kw.get("context") or {}
        merged_ctx = {**deployment_ctx, **caller_ctx}
        if merged_ctx:
            kw["context"] = merged_ctx
        obj = self._object_proxy()

        for attempt in (0, 1):
            uid = self.uid
            try:
                return obj.execute_kw(self._db, uid, self._api_key, model, method, args, kw)
            except xmlrpc.client.Fault as e:
                msg = (e.faultString or "").lower()
                if attempt == 0 and any(t in msg for t in ("session_expired", "invalid_uid", "access denied")):
                    log.warning("Odoo rejected uid=%s (%s); re-authenticating", uid, e.faultCode)
                    self._invalidate_auth()
                    continue
                raise OdooError(f"{model}.{method} failed: {e.faultString}") from e
            except xmlrpc.client.ProtocolError as e:
                raise OdooError(f"{model}.{method} transport error: {e}") from e

    # ── Cross-version domain helpers ──────────────────────────────────────────

    def stockable_domain(self) -> list:
        """Domain fragment for products tracked in inventory, cross-version."""
        return stockable_product_domain(self.version)

    def sellable_product_domain(self) -> list:
        """Domain fragment for anything-you-can-sell (non-service), cross-version."""
        return sellable_product_domain(self.version)


# ── Process-wide singleton ────────────────────────────────────────────────────

_instance: OdooClient | None = None
_instance_lock = threading.Lock()


def get_client() -> OdooClient:
    """Get the singleton `OdooClient` built from the current environment."""
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                s = get_settings()
                _instance = OdooClient(
                    url=s.odoo_url,
                    db=s.odoo_db,
                    login=s.odoo_user,
                    api_key=s.odoo_api_key,
                    company_id=s.odoo_company_id,
                )
    return _instance


# ── Request-scoped vs env-var client resolution ───────────────────────────────

def get_active_client() -> "OdooClient":
    """Return the client for the current request.

    Prefers the context-scoped client set by the Bearer middleware on
    authenticated HTTP requests. Falls back to the env-var singleton for
    stdio transport, background jobs, and tests where no request context
    exists.
    """
    # Imported lazily to avoid a module-level circular with auth.context,
    # which imports OdooClient via TYPE_CHECKING.
    from mezake_mcp.auth.context import current_client
    client = current_client.get()
    if client is not None:
        return client
    return get_client()


# ── Backward-compat shims used by tools/legacy.py ─────────────────────────────

def execute(model: str, method: str, args: list, kw: dict | None = None) -> Any:
    return get_active_client().execute_kw(model, method, args, kw)


def today() -> str:
    return date.today().isoformat()


_x = execute
_today = today
