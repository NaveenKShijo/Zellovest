"""Crypto round-trip + failure tests (no secrets logged)."""

import base64
import os

import pytest
from zellovest_shared.security.crypto import (
    DecryptionError,
    decrypt_token,
    encrypt_token,
    generate_nonce,
)

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


def test_token_pair_nonces_roundtrip() -> None:
    """Access + refresh tokens under separate nonces both decrypt.

    Regression test for the pre-0009 bug where the refresh call's nonce
    was discarded, making the stored refresh token unrecoverable.
    """
    access_nonce = generate_nonce()
    access_ct, _ = encrypt_token("access-123", KEY, access_nonce)
    refresh_ct, refresh_nonce = encrypt_token("refresh-456", KEY)
    assert decrypt_token(access_ct, access_nonce, KEY) == "access-123"
    assert decrypt_token(refresh_ct, refresh_nonce, KEY) == "refresh-456"
    # Cross-nonce decryption must fail (wrong nonce per ciphertext).
    with pytest.raises(DecryptionError):
        decrypt_token(refresh_ct, access_nonce, KEY)
