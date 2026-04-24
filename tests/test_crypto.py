"""Tests for the Fernet encryption wrapper."""

from __future__ import annotations

import pytest

from mezake_mcp.auth.crypto import EncryptionError, decrypt, encrypt, reset_cache
from mezake_mcp.config import get_settings


class TestEncrypt:
    def test_round_trip(self, encryption_key) -> None:
        assert decrypt(encrypt("my-odoo-api-key")) == "my-odoo-api-key"

    def test_ciphertext_is_not_plaintext(self, encryption_key) -> None:
        ciphertext = encrypt("plaintext-secret")
        assert "plaintext-secret" not in ciphertext

    def test_ciphertext_is_non_deterministic(self, encryption_key) -> None:
        # Fernet uses a random IV — two encryptions of the same plaintext
        # must produce different ciphertexts.
        assert encrypt("same") != encrypt("same")

    def test_unicode_round_trip(self, encryption_key) -> None:
        assert decrypt(encrypt("héllo 🔑")) == "héllo 🔑"


class TestConfigurationErrors:
    def test_missing_key_raises(self, monkeypatch) -> None:
        monkeypatch.delenv("ENCRYPTION_KEY", raising=False)
        get_settings.cache_clear()
        reset_cache()
        with pytest.raises(EncryptionError, match="ENCRYPTION_KEY is not set"):
            encrypt("x")
        # Restore for any following tests
        get_settings.cache_clear()

    def test_invalid_key_raises(self, monkeypatch) -> None:
        monkeypatch.setenv("ENCRYPTION_KEY", "not-a-real-fernet-key")
        get_settings.cache_clear()
        reset_cache()
        with pytest.raises(EncryptionError, match="Invalid ENCRYPTION_KEY"):
            encrypt("x")
        get_settings.cache_clear()
        reset_cache()


class TestTampering:
    def test_corrupted_ciphertext_raises(self, encryption_key) -> None:
        ciphertext = encrypt("secret")
        tampered = ciphertext[:-4] + "AAAA"
        with pytest.raises(EncryptionError, match="invalid"):
            decrypt(tampered)

    def test_wrong_key_raises(self, encryption_key, monkeypatch) -> None:
        from cryptography.fernet import Fernet

        from mezake_mcp.auth import crypto

        ciphertext = encrypt("secret")
        # Rotate to a different key and try to decrypt
        monkeypatch.setenv("ENCRYPTION_KEY", Fernet.generate_key().decode())
        get_settings.cache_clear()
        crypto.reset_cache()
        with pytest.raises(EncryptionError):
            decrypt(ciphertext)
