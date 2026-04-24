"""Fernet-based symmetric encryption for data-at-rest.

Used to encrypt Odoo API keys stored in `odoo_connections.api_key_encrypted`
so a leaked DB dump doesn't hand over working Odoo credentials.

Key source: the `ENCRYPTION_KEY` env var. Generate with:

    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

Rotating the key requires re-encrypting every stored ciphertext with the
new key — not automated yet (Phase 6 concern).
"""

from __future__ import annotations

from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken

from mezake_mcp.config import get_settings


class EncryptionError(RuntimeError):
    """Raised when encryption is misconfigured or a ciphertext is invalid."""


@lru_cache(maxsize=1)
def _fernet() -> Fernet:
    settings = get_settings()
    if not settings.encryption_key:
        raise EncryptionError(
            "ENCRYPTION_KEY is not set. Generate one with:\n"
            '  python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"\n'
            "and set it in the deployment environment."
        )
    try:
        return Fernet(settings.encryption_key.encode())
    except Exception as e:
        raise EncryptionError(f"Invalid ENCRYPTION_KEY: {e}") from e


def encrypt(plaintext: str) -> str:
    """Encrypt `plaintext` and return a URL-safe base64 ciphertext string."""
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str) -> str:
    """Decrypt a ciphertext produced by `encrypt()`.

    Raises `EncryptionError` if the ciphertext was tampered with or was
    encrypted with a different key.
    """
    try:
        return _fernet().decrypt(ciphertext.encode()).decode()
    except InvalidToken as e:
        raise EncryptionError(
            "Ciphertext is invalid or was encrypted with a different key"
        ) from e


def reset_cache() -> None:
    """Clear the module-level Fernet cache. For tests only."""
    _fernet.cache_clear()
