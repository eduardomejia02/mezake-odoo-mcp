"""Authentication and authorization primitives.

Phase 4a — encryption (`crypto`), PKCE verification (`pkce`), and one-time
env-var-to-DB bootstrap (`bootstrap`). Phase 4b adds authorization-code
and token storage; Phase 4c mounts the Bearer middleware on `/mcp`.
"""
