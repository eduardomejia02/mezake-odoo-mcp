"""Tests for storage module — DSN normalization and model metadata.

Uses SQLite in-memory; no Postgres needed.
"""

from sqlalchemy import create_engine, inspect

from mezake_mcp.storage.db import normalize_dsn
from mezake_mcp.storage.models import Base


class TestNormalizeDsn:
    def test_heroku_style_postgres_scheme_coerced(self) -> None:
        assert normalize_dsn("postgres://u:p@host:5432/d") == "postgresql+psycopg://u:p@host:5432/d"

    def test_bare_postgresql_gets_psycopg_driver_appended(self) -> None:
        assert (
            normalize_dsn("postgresql://u:p@host:5432/d")
            == "postgresql+psycopg://u:p@host:5432/d"
        )

    def test_explicit_psycopg2_is_left_alone(self) -> None:
        dsn = "postgresql+psycopg2://u:p@host/d"
        assert normalize_dsn(dsn) == dsn

    def test_explicit_psycopg_is_left_alone(self) -> None:
        dsn = "postgresql+psycopg://u:p@host/d"
        assert normalize_dsn(dsn) == dsn


class TestModelMetadata:
    def test_all_tables_create_cleanly_on_sqlite(self) -> None:
        """The schema must be valid SQL on at least one dialect — smoke-test via SQLite."""
        engine = create_engine("sqlite://", future=True)
        Base.metadata.create_all(engine)
        inspector = inspect(engine)
        tables = set(inspector.get_table_names())
        assert tables == {
            "tenants",
            "users",
            "odoo_connections",
            "oauth_codes",
            "oauth_tokens",
            "audit_log",
        }

    def test_users_email_is_unique(self) -> None:
        engine = create_engine("sqlite://", future=True)
        Base.metadata.create_all(engine)
        inspector = inspect(engine)
        constraints = inspector.get_unique_constraints("users")
        assert any("email" in c["column_names"] for c in constraints)
