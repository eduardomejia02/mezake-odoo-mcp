"""Tool registration happens by side-effect when the tool modules are
imported. This package's __init__ imports them all so that a single
`from mezake_mcp import tools` registers every tool on the FastMCP app.

Two tool layers coexist:

  - `generic` (Phase 5): 10 ORM primitives that cover every installed
    Odoo model. Claude uses these to reach models that don't have a
    curated tool — bank statements, journal entries, manufacturing
    orders, any module the customer has installed.

  - `legacy`: 50 domain-specific tools ported from the original v2.0
    server.py (CRM, Accounting, HR, Payroll, Inventory, WhatsApp,
    Projects, Website, Sales, Social). These give Claude a nicer UX
    for the common flows; they'll be progressively retired as the
    generic tools prove out.
"""

from mezake_mcp.tools import generic, legacy  # noqa: F401
