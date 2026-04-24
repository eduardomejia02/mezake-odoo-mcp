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
│   │   └── client.py         XML-RPC wrapper (will become `OdooClient` in Phase 2)
│   └── tools/
│       ├── __init__.py       Imports all tool modules (side-effect registration)
│       └── legacy.py         The 45 v2.0 tools, behavior-preserved
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

`PORT` and `RAILWAY_PUBLIC_DOMAIN` are injected by Railway automatically.

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
```

## Roadmap

- [x] **Phase 1** — Scaffolding (package layout, Dockerfile, pydantic settings, logging). Behavior-preserving.
- [ ] **Phase 2** — `OdooClient` class with UID caching, JSON-RPC option, version detection.
- [ ] **Phase 3** — Postgres-backed storage: tenants, users, connections, tokens, audit log. SQLAlchemy + Alembic migrations.
- [ ] **Phase 4** — Real OAuth 2.1 with PKCE. Each end user binds their own Odoo credentials during onboarding; all Odoo calls run as that user, so company access is enforced by Odoo itself.
- [ ] **Phase 5** — Generic ORM tools (`odoo_search`, `odoo_create`, `odoo_call`, …) covering every module. Retire most curated tools; keep a small set of multi-step workflows (invoice payment reconciliation, lead → opportunity, etc.).
- [ ] **Phase 6** — Per-tenant rate limiting, audit log admin endpoint, tool allow-lists per plan.
- [ ] **Phase 7** — Tests, docs, onboarding UI, Stripe billing integration.

## Security

- The current `/authorize` and `/token` endpoints **do not validate callers** — they are placeholders that satisfy Claude.ai's MCP handshake. Treat the deployed URL as effectively public until Phase 4 lands.
- Never commit credentials — always use Railway environment variables.
- Regenerate the Odoo API key after initial setup.
