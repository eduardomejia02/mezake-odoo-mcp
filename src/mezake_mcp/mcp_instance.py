"""Singleton FastMCP app instance.

Kept in its own module so `server.py` (routes + bootstrap) and
`tools/*.py` (tool registration) can both import `mcp` without a
circular dependency.
"""

from mcp.server.fastmcp import FastMCP

from mezake_mcp.config import get_settings

_settings = get_settings()

mcp = FastMCP(
    "Odoo MCP",
    host="0.0.0.0",
    port=_settings.port,
    stateless_http=True,
)
