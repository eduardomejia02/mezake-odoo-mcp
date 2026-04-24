# Mezake Odoo MCP Server

Claude ↔ Odoo integration over the Model Context Protocol.

> **Status: Rewrite in progress.** The current build preserves the v2.0 behavior (45 curated tools + cosmetic OAuth) but has been restructured into a proper package. Upcoming phases add real OAuth, Postgres-backed sessions, generic ORM tools for full Odoo coverage, and per-user company access control. See [ROADMAP](#roadmap).

## What Claude can do via this MCP

| Module          | Actions                                                  |
|-----------------|----------------------------------------------------------|
| Dashboard       | Full business snapshot                                   |
| CRM             | Search/create/update leads, pipeline, activities         |
| Contacts        | Search, create contacts & companies                      |
| Accounting      | Invoices, bills, payments, journal entries, AR/AP        |
| HR & Payroll    | Employees, leave requests, payslips                      |
| Inventory       | Products, stock levels, low-stock alerts                 |
| WhatsApp        | Read/send messages, chatbot configuration                |
| Projects        | Projects, tasks                                          |
| Sales           | Sales orders                                             |
| Social          | Campaigns, posts, reach/click analytics                  |

## Project layout

```
mezake-odoo-mcp/
├── pyproject.toml            Python project + deps
├── Dockerfile                Railway build target
├── railway.toml              Dockerfile builder + restart policy
├── .env.example              All supported env vars
├── src/mezake_mcp/
│   ├── __main__.py           `python -m mezake_mcp`
│   ├── server.py             FastMCP app, OAuth routes, entry point
│   ├── mcp_instance.py       Singleton FastMCP instance
│   ├── config.py             Pydantic settings (env-driven)
│   ├── logging_setup.py      Logging bootstrap
│   ├── odoo/
│   │   ├── client.py         OdooClient (XML-RPC, cached UID, version probe)
│   │   └── compat.py         Cross-version behavior flags + domain helpers
│   ├── auth/
│   │   ├── crypto.py         Fernet encryption for stored API keys
│   │   ├── pkce.py           RFC 7636 S256 verification
│   │   ├── codes.py          PKCE-bound authorization codes
│   │   ├── tokens.py         Access + refresh bearer tokens
│   │   ├── onboarding.py     HTML form + Odoo credential validation
│   │   ├── routes.py         /authorize, /token, /register, well-known
│   │   └── bootstrap.py      One-time env-var -> DB seeding
│   ├── storage/
│   │   ├── db.py             SQLAlchemy engine + session factory
│   │   ├── models.py         Tenant, User, OdooConnection, OAuthCode, OAuthToken, AuditLog
│   │   └── migrate.py        Programmatic `alembic upgrade head`
│   └── tools/
│       ├── __init__.py       Imports all tool modules (side-effect registration)
│       └── legacy.py         The 50 v2.0 tools, behavior-preserved
├── alembic.ini
├── alembic/
│   ├── env.py                Wired to Base.metadata + DATABASE_URL
│   └── versions/             Migration files
└── tests/
    ├── conftest.py           In-memory SQLite + encryption key fixtures
    ├── test_bootstrap.py     Tests for env-var -> DB seeding
    ├── test_codes.py         Authorization-code issue/redeem, PKCE binding
    ├── test_compat.py        Unit tests for version-compat helpers
    ├── test_crypto.py        Fernet round-trip, tampering, key rotation
    ├── test_onboarding.py    URL normalization, find-or-create, form render
    ├── test_pkce.py          S256 verification incl. RFC 7636 vectors
    ├── test_storage.py       DSN normalizer + model metadata
    └── test_tokens.py        Access/refresh token issue/resolve/refresh/revoke
```

## Deploy to Railway

### 1. Repo already connected

Railway auto-deploys on push to `main`.

### 2. Environment variables

In Railway → your service → **Variables**, set:

| Variable          | Required | Example                                      |
|-------------------|----------|----------------------------------------------|
| `ODOO_URL`        | yes      | `https://mezake.odoo.com`                    |
| `ODOO_DB`         | yes      | `elytekrd-mezake-produccion-14592479`        |
| `ODOO_USER`       | yes      | your Odoo login email                        |
| `ODOO_API_KEY`    | yes      | from Odoo → Settings → Technical → API Keys  |
| `ODOO_COMPANY_ID` | no       | lock this deploy to one company              |
| `ODOO_COMPANY_NAME` | no     | friendly label for the company               |
| `LOG_LEVEL`       | no       | `INFO` (default) / `DEBUG`                   |

`PORT` and `RAILWAY_PUBLIC_DOMAIN` are injected by Railway automatically. `DATABASE_URL` is injected when you add the Railway Postgres plugin — see **Storage** below.

### Storage (Postgres)

Phase 3+ uses Postgres for OAuth sessions, per-user Odoo connections, and the audit log. To attach it:

1. Railway project → **+ New → Database → Add PostgreSQL**
2. Railway auto-wires `DATABASE_URL` to your app service. Nothing to copy.
3. Next deploy (or restart) runs `alembic upgrade head` automatically on boot, creating the schema.

Until you attach Postgres, the server runs in "storage disabled" mode and behaves exactly like Phase 2.

### 3. Public domain

Railway → service → **Settings → Networking → Generate Domain**. Your MCP URL:

```
https://your-app.up.railway.app/mcp
```

### 4. Connect to Claude.ai

Claude.ai → Settings → Integrations → Add MCP server → paste the URL.

## Local development

```bash
# Create a venv and install (editable)
python -m venv .venv
source .venv/bin/activate          # PowerShell: .venv\Scripts\Activate.ps1
pip install -e ".[dev]"

# Copy and fill in .env
cp .env.example .env

# Run the server
python -m mezake_mcp

# Smoke test
curl http://localhost:8000/health

# Run tests
pytest
```

## Roadmap

- [x] **Phase 1** — Scaffolding (package layout, Dockerfile, pydantic settings, logging). Behavior-preserving.
- [x] **Phase 2** — `OdooClient` class with UID caching + version probe + `compat` module for cross-version behavior (e.g. v17+ product.type/is_storable split). First unit tests.
- [x] **Phase 3** — Postgres-backed storage: tenants, users, connections, tokens, audit log. SQLAlchemy 2.0 + Alembic migrations (auto-applied on startup). Storage is optional — server still boots without `DATABASE_URL`.
- [x] **Phase 4a** — Auth primitives: Fernet encryption for stored API keys, PKCE (S256) verification, and one-time bootstrap that seeds the default tenant/user/connection from env vars on first startup. Requires `ENCRYPTION_KEY`.
- [x] **Phase 4b** — Real OAuth endpoints: onboarding HTML form at `/authorize`, PKCE-bound authorization codes, access + refresh bearer tokens persisted in Postgres (as SHA-256 hashes). Hitting `/authorize` shows a form asking for Odoo URL/DB/login/API key; on submit the creds are validated against the user's Odoo and an auth code is redirected back to Claude.ai.
- [ ] **Phase 4c** — Bearer middleware cut-over: every `/mcp` request gated by a real token; per-request `OdooClient` loaded from the user's encrypted credentials.
- [ ] **Phase 5** — Generic ORM tools (`odoo_search`, `odoo_create`, `odoo_call`, …) covering every module. Retire most curated tools; keep a small set of multi-step workflows (invoice payment reconciliation, lead → opportunity, etc.).
- [ ] **Phase 6** — Per-tenant rate limiting, audit log admin endpoint, tool allow-lists per plan.
- [ ] **Phase 7** — Tests, docs, onboarding UI, Stripe billing integration.

## Security

- As of Phase 4b, `/authorize` and `/token` implement real OAuth 2.1 + PKCE: authorization codes are PKCE-bound, single-use, and expire after 60 seconds; access tokens last 1 hour, refresh tokens 30 days; both are stored as SHA-256 hashes. **However, `/mcp` itself still accepts any bearer** — the Bearer middleware that enforces tokens on MCP traffic lands in Phase 4c. Don't treat the deployed URL as secured until then.
- Stored Odoo API keys are encrypted at rest with Fernet (AES-128-CBC + HMAC-SHA256). Rotating `ENCRYPTION_KEY` invalidates all stored keys — users must re-authenticate.
- Never commit credentials — always use Railway environment variables.
- Regenerate the Odoo API key after initial setup.
