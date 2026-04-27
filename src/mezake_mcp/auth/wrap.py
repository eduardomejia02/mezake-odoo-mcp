"""Wrap every registered FastMCP tool with audit logging + plan-policy.

Called once at startup, AFTER the tool modules have been imported (so
the registry is fully populated). Replaces each `Tool.fn` with a
wrapper that:

  1. Reads the authenticated user_id from the request-scoped ContextVar.
  2. Checks plan policy via `auth.policy.check_tool_allowed` —
     denial returns the structured error to Claude *without* hitting Odoo.
  3. Times the underlying call.
  4. Records exactly one row in `audit_log` for success / failure /
     denial — best-effort, never raises out of the audit path.

For `odoo_*` generic tools, model + method are extracted from the
kwargs so the audit row carries them; legacy curated tools leave those
columns NULL.
"""

from __future__ import annotations

import asyncio
import functools
import logging
import time
from typing import Any

from mezake_mcp import audit
from mezake_mcp.auth.context import current_user_id
from mezake_mcp.auth.policy import ToolNotAllowedError, check_tool_allowed

log = logging.getLogger(__name__)


def wrap_all_tools(mcp) -> int:
    """Replace every registered tool's `fn` with an audited + policy-gated
    wrapper. Returns the number of tools wrapped.

    Idempotent: re-wrapping an already-wrapped function is detected via a
    sentinel attribute and skipped, so calling this twice is a no-op.
    """
    try:
        tools = mcp._tool_manager._tools
    except AttributeError:
        log.error(
            "FastMCP layout changed — could not find _tool_manager._tools. "
            "Audit + policy enforcement is NOT active."
        )
        return 0

    wrapped = 0
    for name, tool in tools.items():
        if getattr(tool.fn, "_mezake_wrapped", False):
            continue
        tool.fn = _make_wrapper(name, tool.fn)
        wrapped += 1

    log.info("Wrapped %d tools with audit + policy", wrapped)
    return wrapped


def _extract_model_method(kwargs: dict[str, Any]) -> tuple[str | None, str | None]:
    """Pull `model` and `method` out of the bound kwargs if present.
    Generic ORM tools all expose `model`; only `odoo_call` exposes `method`.
    """
    model = kwargs.get("model") if isinstance(kwargs.get("model"), str) else None
    method = kwargs.get("method") if isinstance(kwargs.get("method"), str) else None
    return model, method


def _make_wrapper(tool_name: str, original_fn):
    """Build either an async or sync wrapper depending on the original."""
    if asyncio.iscoroutinefunction(original_fn):

        @functools.wraps(original_fn)
        async def async_wrapper(**kwargs):
            return await _async_call(tool_name, original_fn, kwargs)

        async_wrapper._mezake_wrapped = True  # type: ignore[attr-defined]
        return async_wrapper

    @functools.wraps(original_fn)
    def sync_wrapper(**kwargs):
        return _sync_call(tool_name, original_fn, kwargs)

    sync_wrapper._mezake_wrapped = True  # type: ignore[attr-defined]
    return sync_wrapper


def _sync_call(tool_name: str, fn, kwargs: dict) -> Any:
    user_id = current_user_id.get()
    model, method = _extract_model_method(kwargs)

    try:
        check_tool_allowed(user_id, tool_name)
    except ToolNotAllowedError as e:
        audit.record_call(
            user_id, tool_name, status="denied", duration_ms=0,
            odoo_model=model, odoo_method=method, error=str(e),
        )
        # Surface as a tool-execution error Claude can show to the user.
        raise

    start = time.perf_counter()
    try:
        result = fn(**kwargs)
    except Exception as e:
        elapsed_ms = int((time.perf_counter() - start) * 1000)
        audit.record_call(
            user_id, tool_name, status="error", duration_ms=elapsed_ms,
            odoo_model=model, odoo_method=method, error=str(e),
        )
        raise

    elapsed_ms = int((time.perf_counter() - start) * 1000)
    audit.record_call(
        user_id, tool_name, status="ok", duration_ms=elapsed_ms,
        odoo_model=model, odoo_method=method,
    )
    return result


async def _async_call(tool_name: str, fn, kwargs: dict) -> Any:
    user_id = current_user_id.get()
    model, method = _extract_model_method(kwargs)

    try:
        check_tool_allowed(user_id, tool_name)
    except ToolNotAllowedError as e:
        audit.record_call(
            user_id, tool_name, status="denied", duration_ms=0,
            odoo_model=model, odoo_method=method, error=str(e),
        )
        raise

    start = time.perf_counter()
    try:
        result = await fn(**kwargs)
    except Exception as e:
        elapsed_ms = int((time.perf_counter() - start) * 1000)
        audit.record_call(
            user_id, tool_name, status="error", duration_ms=elapsed_ms,
            odoo_model=model, odoo_method=method, error=str(e),
        )
        raise

    elapsed_ms = int((time.perf_counter() - start) * 1000)
    audit.record_call(
        user_id, tool_name, status="ok", duration_ms=elapsed_ms,
        odoo_model=model, odoo_method=method,
    )
    return result
