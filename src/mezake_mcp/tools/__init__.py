"""Tool registration happens by side-effect when the tool modules are
imported. This package's __init__ imports them all so that a single
`from mezake_mcp import tools` registers every tool on the FastMCP app.

Phase 1: only `legacy` is wired up — the existing 45 tools, behavior
preserved. Later phases will add `generic` (ORM primitives) and
`workflows/` (curated multi-step flows), then progressively retire
`legacy`.
"""

from mezake_mcp.tools import legacy  # noqa: F401
