"""Tests for PKCE verification."""

from __future__ import annotations

import base64
import hashlib

from mezake_mcp.auth.pkce import verify


def _challenge_for(verifier: str) -> str:
    """Compute the expected S256 challenge for a given verifier."""
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


# RFC 7636 Appendix B sample vectors
RFC_VERIFIER = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
RFC_CHALLENGE = "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"


class TestVerify:
    def test_rfc_7636_known_vector(self) -> None:
        assert verify(RFC_VERIFIER, RFC_CHALLENGE) is True

    def test_matching_pair_verifies(self) -> None:
        verifier = "a" * 64
        assert verify(verifier, _challenge_for(verifier)) is True

    def test_mismatched_challenge_fails(self) -> None:
        assert verify("a" * 64, _challenge_for("b" * 64)) is False

    def test_plain_method_is_rejected(self) -> None:
        """'plain' method is explicitly not supported — same verifier +
        challenge must still fail when method='plain'."""
        value = "a" * 64
        assert verify(value, value, method="plain") is False

    def test_unknown_method_is_rejected(self) -> None:
        assert verify("a" * 64, _challenge_for("a" * 64), method="S384") is False

    def test_verifier_too_short_fails(self) -> None:
        short = "a" * 42
        assert verify(short, _challenge_for(short)) is False

    def test_verifier_too_long_fails(self) -> None:
        too_long = "a" * 129
        assert verify(too_long, _challenge_for(too_long)) is False

    def test_verifier_at_min_length_works(self) -> None:
        v = "a" * 43
        assert verify(v, _challenge_for(v)) is True

    def test_verifier_at_max_length_works(self) -> None:
        v = "a" * 128
        assert verify(v, _challenge_for(v)) is True
