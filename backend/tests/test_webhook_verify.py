"""HMAC webhook signature verification tests."""

import hashlib
import hmac

import pytest

from zellovest_shared.security.webhook import InvalidSignatureError, verify_signature

SECRET = "whsec-test"
BODY = b'{"event_id":"evt_123","type":"transaction.created"}'


def _sig(body: bytes) -> str:
    return hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()


def test_valid_hex_signature() -> None:
    """Correct hex signature verifies without error."""
    verify_signature(SECRET, BODY, _sig(BODY))


def test_valid_prefixed_signature() -> None:
    """sha256= prefixed signature verifies without error."""
    verify_signature(SECRET, BODY, f"sha256={_sig(BODY)}")


def test_wrong_signature_rejected() -> None:
    """Tampered body raises InvalidSignatureError."""
    with pytest.raises(InvalidSignatureError):
        verify_signature(SECRET, b"tampered", _sig(BODY))


def test_missing_signature_rejected() -> None:
    """Missing signature raises InvalidSignatureError."""
    with pytest.raises(InvalidSignatureError):
        verify_signature(SECRET, BODY, None)
