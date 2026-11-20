"""HMAC confirmation tokens for high-risk MCP actions.

The Agentic Reasoning Service mints a token only after the signed-in user
explicitly confirms the exact tool + parameters. The MCP-3 server re-derives
the signed payload and rejects expired, tampered, or replayed-with-different-
parameters tokens. Tokens are stateless (no shared session store needed) and
bound to the tenant, tool, idempotency key, and a digest of the arguments.

See ``PRD.md`` section 25.4 ("High-risk operations must require explicit human
confirmation").
"""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

TOKEN_VERSION = "v1"
DEFAULT_TTL_SECONDS = 900


class ConfirmationError(ValueError):
    """Raised when a confirmation token is malformed, expired, or invalid."""


def canonical_json(value: Any) -> str:
    """Serialize a value deterministically for hashing and signing.

    Args:
        value: JSON-serializable payload.

    Returns:
        Compact JSON with sorted keys and no insignificant whitespace.
    """
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def parameters_digest(parameters: Mapping[str, Any]) -> str:
    """Return a stable SHA-256 digest of the tool arguments.

    Args:
        parameters: Tool arguments as received by the host.

    Returns:
        Hex-encoded digest. Volatile keys (confirmation token, dry-run flag)
        are excluded so a token can be minted before ``dry_run`` flips.
    """
    excluded = {"confirmation_token", "dry_run"}
    payload = {key: value for key, value in parameters.items() if key not in excluded}
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def _sign(secret: str, payload: str) -> str:
    """Return the hex HMAC-SHA256 signature for one payload string."""
    return hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()


def _payload(
    *, tenant_id: str, tool_name: str, idempotency_key: str, digest: str, expires_at: int
) -> str:
    """Build the canonical signed payload for one confirmation."""
    return canonical_json(
        {
            "tenant_id": tenant_id,
            "tool": tool_name,
            "idempotency_key": idempotency_key,
            "parameters": digest,
            "expires_at": expires_at,
            "version": TOKEN_VERSION,
        }
    )


def mint_confirmation_token(
    *,
    secret: str,
    tenant_id: str,
    tool_name: str,
    idempotency_key: str,
    parameters: Mapping[str, Any],
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
    now: float | None = None,
) -> tuple[str, int]:
    """Mint a short-lived confirmation token for a high-risk tool call.

    Args:
        secret: Shared HMAC secret configured on the host and MCP-3.
        tenant_id: Tenant that owns the action.
        tool_name: High-risk tool being confirmed.
        idempotency_key: Client-supplied idempotency key for the action.
        parameters: Exact arguments the human reviewed.
        ttl_seconds: Token lifetime; capped at one hour.
        now: Injectable clock for tests.

    Returns:
        Tuple of ``(token, expires_at_epoch_seconds)``.

    Raises:
        ValueError: If the secret is empty or the TTL is non-positive.
    """
    if not secret:
        raise ValueError("confirmation secret is not configured")
    if ttl_seconds <= 0:
        raise ValueError("confirmation ttl must be positive")
    ttl = min(int(ttl_seconds), 3600)
    expires_at = math.floor(now if now is not None else time.time()) + ttl
    payload = _payload(
        tenant_id=tenant_id,
        tool_name=tool_name,
        idempotency_key=idempotency_key,
        digest=parameters_digest(parameters),
        expires_at=expires_at,
    )
    return f"{TOKEN_VERSION}.{expires_at}.{_sign(secret, payload)}", expires_at


def verify_confirmation_token(
    *,
    secret: str,
    token: str,
    tenant_id: str,
    tool_name: str,
    idempotency_key: str,
    parameters: Mapping[str, Any],
    now: float | None = None,
) -> None:
    """Verify a confirmation token, raising on any mismatch.

    Args:
        secret: Shared HMAC secret configured on MCP-3.
        token: Token produced by :func:`mint_confirmation_token`.
        tenant_id: Tenant resolved from the authenticated request.
        tool_name: Tool being executed.
        idempotency_key: Idempotency key supplied with this execution.
        parameters: Arguments supplied with this execution.
        now: Injectable clock for tests.

    Raises:
        ConfirmationError: When the token is malformed, expired, belongs to a
            different tenant/tool/idempotency key, or signs different
            parameters.
    """
    if not secret:
        raise ConfirmationError("confirmation is not configured")
    if not token:
        raise ConfirmationError("confirmation_token is required for high-risk actions")
    parts = token.split(".")
    if len(parts) != 3 or parts[0] != TOKEN_VERSION:
        raise ConfirmationError("malformed confirmation token")
    try:
        expires_at = int(parts[1])
    except ValueError as exc:
        raise ConfirmationError("malformed confirmation token") from exc
    current = math.floor(now if now is not None else time.time())
    if expires_at <= current:
        raise ConfirmationError("confirmation token has expired")
    payload = _payload(
        tenant_id=tenant_id,
        tool_name=tool_name,
        idempotency_key=idempotency_key,
        digest=parameters_digest(parameters),
        expires_at=expires_at,
    )
    expected = _sign(secret, payload)
    if not hmac.compare_digest(expected, parts[2]):
        raise ConfirmationError(
            "confirmation token does not match this tenant, action, or parameters"
        )


@dataclass(frozen=True)
class ConfirmationRequest:
    """Human confirmation summary returned to the UI before execution."""

    tool_name: str
    risk_class: str
    parameters_preview: dict[str, Any]
    expires_at: int
    token: str
