"""Programmatic `alembic upgrade head`.

Called from `server.main()` on startup. No-op if storage is disabled.
"""

from __future__ import annotations

import logging
import pathlib

from alembic import command
from alembic.config import Config

from mezake_mcp.storage import db

log = logging.getLogger(__name__)


def upgrade_to_head() -> None:
    """Apply every pending migration up to HEAD. No-op if storage is off."""
    if not db.is_enabled():
        return
    cfg = Config(str(_find_ini()))
    log.info("Running migrations (alembic upgrade head)")
    command.upgrade(cfg, "head")
    log.info("Migrations complete")


def _find_ini() -> pathlib.Path:
    """Locate `alembic.ini`.

    Checks (in order):
      - CWD (`python -m mezake_mcp` from the project root during dev)
      - The Docker image root at `/app`
      - The package-relative path (…/mezake-odoo-mcp/alembic.ini)
    """
    candidates = [
        pathlib.Path.cwd() / "alembic.ini",
        pathlib.Path("/app/alembic.ini"),
        pathlib.Path(__file__).resolve().parents[3] / "alembic.ini",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(
        f"alembic.ini not found. Looked in: {', '.join(str(c) for c in candidates)}"
    )
