"""HMAC-SHA256 webhook signature verification (constant-time)."""

import base64
import hashlib
import hmac


class InvalidSignatureError(Exception):
    """Raised when the webhook signature is missing or does not match."""


def _candidate_signatures(secret: str, raw_body: bytes) -> set[str]:
    """Return accepted signature encodings (hex + base64, raw + sha256= prefix)."""
    digest = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).digest()
    hex_sig = digest.hex()
    b64_sig = base64.b64encode(digest).decode()
    return {hex_sig, f"sha256={hex_sig}", b64_sig, f"sha256={b64_sig}"}


def verify_signature(secret: str, raw_body: bytes, provided: str | None) -> None:
    """Verify a webhook signature against the raw request body.

    Args:
        secret: Shared webhook secret.
        raw_body: Exact raw request bytes (must be read before JSON parsing).
        provided: Signature header value sent by the provider.

    Raises:
        InvalidSignatureError: If missing or mismatched.
    """
    if not provided:
        raise InvalidSignatureError("missing webhook signature")
    candidates = _candidate_signatures(secret, raw_body)
    provided = provided.strip()
    for candidate in candidates:
        if hmac.compare_digest(candidate, provided):
            return
    raise InvalidSignatureError("webhook signature mismatch")
