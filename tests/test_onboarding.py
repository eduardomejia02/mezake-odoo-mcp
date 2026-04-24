"""Tests for the onboarding URL-normalization and user/connection persistence.

Live Odoo validation is tested end-to-end against Railway after deploy;
this file only covers the pure logic.
"""

from __future__ import annotations

import pytest
from sqlalchemy import func, select

from mezake_mcp.auth.crypto import decrypt
from mezake_mcp.auth.onboarding import (
    OnboardingInput,
    find_or_create_user_and_connection,
    render_form,
)
from mezake_mcp.storage.db import session_scope
from mezake_mcp.storage.models import OdooConnection, Tenant, User


class TestNormalizeUrl:
    def test_adds_https_if_missing(self) -> None:
        assert OnboardingInput("mezake.odoo.com", "x", "x", "x").normalized_url() == "https://mezake.odoo.com"

    def test_keeps_existing_https(self) -> None:
        assert OnboardingInput("https://mezake.odoo.com", "x", "x", "x").normalized_url() == "https://mezake.odoo.com"

    def test_keeps_existing_http(self) -> None:
        assert OnboardingInput("http://localhost:8069", "x", "x", "x").normalized_url() == "http://localhost:8069"

    def test_strips_trailing_slash(self) -> None:
        assert OnboardingInput("https://mezake.odoo.com/", "x", "x", "x").normalized_url() == "https://mezake.odoo.com"

    def test_strips_surrounding_whitespace(self) -> None:
        assert OnboardingInput("  mezake.odoo.com  ", "x", "x", "x").normalized_url() == "https://mezake.odoo.com"


class TestFindOrCreate:
    def test_creates_new_tenant_user_and_connection(self, inmemory_db, encryption_key) -> None:
        uid = find_or_create_user_and_connection(OnboardingInput(
            odoo_url="https://acme.odoo.com",
            odoo_db="acme-prod",
            odoo_login="owner@acme.com",
            odoo_api_key="raw-api-key",
        ))
        with session_scope() as session:
            assert session.scalar(select(func.count()).select_from(Tenant)) == 1
            assert session.scalar(select(func.count()).select_from(User)) == 1
            conn = session.scalar(select(OdooConnection))
            assert conn.url == "https://acme.odoo.com"
            assert conn.db == "acme-prod"
            assert conn.login == "owner@acme.com"
            assert decrypt(conn.api_key_encrypted) == "raw-api-key"
            assert conn.user_id == uid

    def test_re_auth_updates_same_connection_in_place(self, inmemory_db, encryption_key) -> None:
        # First pass
        uid_1 = find_or_create_user_and_connection(OnboardingInput(
            odoo_url="https://acme.odoo.com",
            odoo_db="acme-prod",
            odoo_login="owner@acme.com",
            odoo_api_key="key-v1",
        ))
        # Same email, rotated key + different DB
        uid_2 = find_or_create_user_and_connection(OnboardingInput(
            odoo_url="https://acme.odoo.com",
            odoo_db="acme-staging",
            odoo_login="owner@acme.com",
            odoo_api_key="key-v2",
        ))
        assert uid_1 == uid_2
        with session_scope() as session:
            # Still exactly one user and one connection
            assert session.scalar(select(func.count()).select_from(User)) == 1
            assert session.scalar(select(func.count()).select_from(OdooConnection)) == 1
            conn = session.scalar(select(OdooConnection))
            assert conn.db == "acme-staging"
            assert decrypt(conn.api_key_encrypted) == "key-v2"

    def test_different_emails_get_separate_users(self, inmemory_db, encryption_key) -> None:
        uid_a = find_or_create_user_and_connection(OnboardingInput(
            "acme.odoo.com", "db", "a@acme.com", "k1",
        ))
        uid_b = find_or_create_user_and_connection(OnboardingInput(
            "beta.odoo.com", "db", "b@beta.com", "k2",
        ))
        assert uid_a != uid_b
        with session_scope() as session:
            assert session.scalar(select(func.count()).select_from(User)) == 2
            # Same tenant for both — the onboarding flow is single-tenant for now
            assert session.scalar(select(func.count()).select_from(Tenant)) == 1


class TestRenderForm:
    def test_includes_hidden_oauth_params(self) -> None:
        html = render_form(
            client_id="client-1",
            redirect_uri="https://claude.ai/cb",
            state="xyz",
            code_challenge="ch",
            code_challenge_method="S256",
            scope="mcp",
        )
        assert 'name="client_id" value="client-1"' in html
        assert 'name="redirect_uri" value="https://claude.ai/cb"' in html
        assert 'name="state" value="xyz"' in html
        assert 'name="code_challenge" value="ch"' in html

    def test_error_message_is_displayed(self) -> None:
        html = render_form(
            client_id="c", redirect_uri="r", state="", code_challenge="ch",
            code_challenge_method="S256", scope="mcp",
            error="Odoo said no.",
        )
        assert 'class="error"' in html
        assert "Odoo said no." in html

    def test_error_message_is_html_escaped(self) -> None:
        html = render_form(
            client_id="c", redirect_uri="r", state="", code_challenge="ch",
            code_challenge_method="S256", scope="mcp",
            error="<script>alert('xss')</script>",
        )
        assert "<script>alert" not in html
        assert "&lt;script&gt;" in html

    def test_preserves_user_odoo_input_on_error(self) -> None:
        html = render_form(
            client_id="c", redirect_uri="r", state="", code_challenge="ch",
            code_challenge_method="S256", scope="mcp",
            error="nope",
            odoo_url="https://acme.odoo.com",
            odoo_db="acme-prod",
            odoo_login="me@acme.com",
        )
        assert 'value="https://acme.odoo.com"' in html
        assert 'value="acme-prod"' in html
        assert 'value="me@acme.com"' in html
