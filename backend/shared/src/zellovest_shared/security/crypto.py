"""Cryptography helpers for AES-256-GCM token encryption."""

import base64
import os
from typing import Final

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

# AES-GCM uses 12-byte nonces (96 bits) - NIST recommended
NONCE_SIZE: Final = 12
KEY_SIZE: Final = 32  # 256 bits


class DecryptionError(Exception):
    """Raised when ciphertext fails authentication (wrong key / tampered data)."""


def generate_key() -> str:
    """Generate a new AES-256 key, returned as base64 string for env storage."""
    return base64.b64encode(os.urandom(KEY_SIZE)).decode()


def generate_nonce() -> bytes:
    """Generate a cryptographically random 12-byte nonce."""
    return os.urandom(NONCE_SIZE)


def encrypt_token(plaintext: str, key_b64: str, nonce: bytes | None = None) -> tuple[bytes, bytes]:
    """Encrypt a token string with AES-256-GCM.

    Args:
        plaintext: The token to encrypt.
        key_b64: Base64-encoded 32-byte encryption key.
        nonce: Optional 12-byte nonce (generated if not provided).

    Returns:
        Tuple of (ciphertext, nonce).
    """
    key = base64.b64decode(key_b64)
    if len(key) != KEY_SIZE:
        raise ValueError(f"Key must be {KEY_SIZE} bytes, got {len(key)}")

    if nonce is None:
        nonce = generate_nonce()
    elif len(nonce) != NONCE_SIZE:
        raise ValueError(f"Nonce must be {NONCE_SIZE} bytes, got {len(nonce)}")

    aesgcm = AESGCM(key)
    ciphertext = aesgcm.encrypt(nonce, plaintext.encode(), None)
    return ciphertext, nonce


def decrypt_token(ciphertext: bytes, nonce: bytes, key_b64: str) -> str:
    """Decrypt a token encrypted with ``encrypt_token``.

    Args:
        ciphertext: The encrypted token bytes.
        nonce: The 12-byte nonce used during encryption.
        key_b64: Base64-encoded 32-byte encryption key.

    Returns:
        The decrypted token string.

    Raises:
        DecryptionError: If authentication fails (wrong key / tampered data).
    """
    key = base64.b64decode(key_b64)
    if len(key) != KEY_SIZE:
        raise ValueError(f"Key must be {KEY_SIZE} bytes, got {len(key)}")

    if len(nonce) != NONCE_SIZE:
        raise ValueError(f"Nonce must be {NONCE_SIZE} bytes, got {len(nonce)}")

    aesgcm = AESGCM(key)
    try:
        plaintext = aesgcm.decrypt(nonce, ciphertext, None)
    except InvalidTag as exc:
        raise DecryptionError("token authentication failed") from exc
    return plaintext.decode()