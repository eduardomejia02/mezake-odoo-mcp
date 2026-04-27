"""Runtime configuration loaded from environment variables.

Uses pydantic-settings so env var names map 1:1 to attribute names
(case-insensitive). `get_settings()` is cached — settings are read once
at import time.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── Odoo connection ───────────────────────────────────────────────────────
    odoo_url: str = "https://yourcompany.odoo.com"
    odoo_db: str = ""
    odoo_user: str = ""
    odoo_api_key: str = ""

    # Optional company lock (set at deploy time via env)
    odoo_company_id: int | None = None
    odoo_company_name: str = ""

    # ── Server ────────────────────────────────────────────────────────────────
    port: int = 8000
    railway_public_domain: str = "localhost"
    log_level: str = "INFO"

    # ── Storage (Phase 3) ─────────────────────────────────────────────────────
    database_url: str | None = None

    # ── Auth (Phase 4) ────────────────────────────────────────────────────────
    encryption_key: str | None = None

    # ── Rate limiting (Phase 6b) ──────────────────────────────────────────────
    # Token bucket per authenticated user: `capacity` is the burst size and
    # `refill_per_second` is the sustained rate. Defaults: 30-call burst
    # plus 120 calls/min sustained.
    rate_limit_capacity: int = 30
    rate_limit_refill_per_second: float = 2.0

    # ── Admin (Phase 6c) ──────────────────────────────────────────────────────
    # Comma-separated list of email addresses with access to /admin/*
    # endpoints. Empty (default) means no admin endpoints are reachable.
    # Match is case-insensitive on the user's stored email.
    admin_emails: str = ""

    @property
    def admin_email_set(self) -> set[str]:
        if not self.admin_emails:
            return set()
        return {e.strip().lower() for e in self.admin_emails.split(",") if e.strip()}

    @property
    def base_url(self) -> str:
        if self.railway_public_domain in ("localhost", ""):
            return f"http://localhost:{self.port}"
        return f"https://{self.railway_public_domain}"

    @property
    def active_company_label(self) -> str:
        if self.odoo_company_name:
            return self.odoo_company_name
        if self.odoo_company_id:
            return f"Company {self.odoo_company_id}"
        return "All Companies"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
