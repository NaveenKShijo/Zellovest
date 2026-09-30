"""Crypto round-trip + failure tests (no secrets logged)."""

import base64
import os

import pytest

from zellovest_shared.security.crypto import DecryptionError, decrypt_token, encrypt_token

KEY = base64.b64encode(os.urandom(32)).decode()
WRONG_KEY = base64.b64encode(os.urandom(32)).decode()


def test_encrypt_decrypt_roundtrip() -> None:
    """Ciphertext decrypts to the original token with the same key."""
    ciphertext, nonce = encrypt_token("secret-token-123", KEY)
    assert decrypt_token(ciphertext, nonce, KEY) == "secret-token-123"
    assert len(nonce) == 12


def test_decrypt_wrong_key_fails() -> None:
    """Wrong key raises DecryptionError (GCM auth failure)."""
    ciphertext, nonce = encrypt_token("secret-token-123", KEY)
    with pytest.raises(DecryptionError):
        decrypt_token(ciphertext, nonce, WRONG_KEY)


def test_decrypt_tampered_fails() -> None:
    """Tampered ciphertext raises DecryptionError."""
    ciphertext, nonce = encrypt_token("secret-token-123", KEY)
    tampered = bytearray(ciphertext)
    tampered[0] ^= 0xFF
    with pytest.raises(DecryptionError):
        decrypt_token(bytes(tampered), nonce, KEY)


def test_nonce_unique_per_encryption() -> None:
    """Each encryption uses a fresh random nonce."""
    _, nonce1 = encrypt_token("same", KEY)
    _, nonce2 = encrypt_token("same", KEY)
    assert nonce1 != nonce2
