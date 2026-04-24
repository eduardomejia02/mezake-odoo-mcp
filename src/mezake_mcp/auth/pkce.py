"""PKCE (RFC 7636) verification.

Only the `S256` method is supported — `plain` is explicitly rejected because
it provides no protection against a leaked authorization code.
"""

from __future__ import annotations

import base64
import hashlib


def verify(code_verifier: str, code_challenge: str, method: str = "S256") -> bool:
    """Return True iff `BASE64URL(SHA256(code_verifier))` equals `code_challenge`.

    `code_verifier` must be 43–128 characters per RFC 7636 §4.1. Inputs
    that violate this length bound fail verification; they are not an
    exceptional condition worth raising for.
    """
    if method != "S256":
        return False
    if not (43 <= len(code_verifier) <= 128):
        return False
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    expected = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return expected == code_challenge
