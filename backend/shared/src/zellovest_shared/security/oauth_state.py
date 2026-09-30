"""OAuth state management with Redis-backed TTL storage.

Prevents CSRF by binding authorization requests to short-lived,
single-use state tokens stored in Redis.
"""

import base64
import hashlib
import json
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final

import redis

from zellovest_shared.config import get_settings


@dataclass(slots=True)
class OAuthState:
    """OAuth authorization state payload."""

    state: str
    tenant_id: str
    provider: str
    redirect_uri: str
    scopes: list[str]
    created_at: datetime
    pkce_verifier: str | None = None


class OAuthStateStore:
    """Redis-backed OAuth state store with TTL and single-use semantics."""

    _PREFIX: Final = "oauth:state:"

    def __init__(self, redis_client: redis.Redis | None = None):
        self._redis = redis_client or self._create_client()

    def _create_client(self) -> redis.Redis:
        settings = get_settings()
        return redis.Redis.from_url(settings.redis_url, decode_responses=True)

    def _key(self, state: str) -> str:
        return f"{self._PREFIX}{state}"

    def create(
        self,
        tenant_id: str,
        provider: str,
        redirect_uri: str,
        scopes: list[str],
        pkce_verifier: str | None = None,
    ) -> OAuthState:
        """Create and store a new OAuth state."""
        state_token = secrets.token_urlsafe(32)
        state = OAuthState(
            state=state_token,
            tenant_id=tenant_id,
            provider=provider,
            redirect_uri=redirect_uri,
            scopes=scopes,
            created_at=datetime.now(UTC),
            pkce_verifier=pkce_verifier,
        )
        ttl = get_settings().oauth_state_ttl_seconds
        self._redis.setex(
            self._key(state_token),
            ttl,
            json.dumps(
                {
                    "state": state.state,
                    "tenant_id": state.tenant_id,
                    "provider": state.provider,
                    "redirect_uri": state.redirect_uri,
                    "scopes": state.scopes,
                    "created_at": state.created_at.isoformat(),
                    "pkce_verifier": state.pkce_verifier,
                }
            ),
        )
        return state

    def consume(self, state: str) -> OAuthState | None:
        """Retrieve and delete a state (single-use)."""
        key = self._key(state)
        data = self._redis.get(key)
        if data is None:
            return None
        self._redis.delete(key)
        payload = json.loads(data)
        return OAuthState(
            state=payload["state"],
            tenant_id=payload["tenant_id"],
            provider=payload["provider"],
            redirect_uri=payload["redirect_uri"],
            scopes=payload["scopes"],
            created_at=datetime.fromisoformat(payload["created_at"]),
            pkce_verifier=payload.get("pkce_verifier"),
        )

    def get(self, state: str) -> OAuthState | None:
        """Peek at a state without consuming (for debugging)."""
        data = self._redis.get(self._key(state))
        if data is None:
            return None
        payload = json.loads(data)
        return OAuthState(
            state=payload["state"],
            tenant_id=payload["tenant_id"],
            provider=payload["provider"],
            redirect_uri=payload["redirect_uri"],
            scopes=payload["scopes"],
            created_at=datetime.fromisoformat(payload["created_at"]),
            pkce_verifier=payload.get("pkce_verifier"),
        )

    def generate_pkce_pair(self) -> tuple[str, str]:
        """Generate PKCE code verifier and challenge (RFC 7636)."""
        verifier = secrets.token_urlsafe(64)  # 43-128 chars
        challenge = hashlib.sha256(verifier.encode()).digest()
        challenge_b64 = base64.urlsafe_b64encode(challenge).decode().rstrip("=")
        return verifier, challenge_b64


STATE_PREFIX = "oauth:state:"


def create_state(redis_client: redis.Redis, tenant_id: str, ttl_seconds: int = 600) -> str:
    """Generate a secure state token and persist it in Redis.

    Args:
        redis_client: Redis client.
        tenant_id: Tenant that initiated the OAuth flow.
        ttl_seconds: Expiry window for the state token.

    Returns:
        URL-safe state string to embed in the authorization URL.
    """
    state = secrets.token_urlsafe(32)
    redis_client.setex(f"{STATE_PREFIX}{state}", ttl_seconds, tenant_id)
    return state


def consume_state(redis_client: redis.Redis, state: str) -> str | None:
    """Atomically consume a state token, returning its tenant_id.

    Args:
        redis_client: Redis client.
        state: State token from the OAuth callback.

    Returns:
        The bound tenant_id, or None if unknown/expired/reused.
    """
    key = f"{STATE_PREFIX}{state}"
    tenant_raw = redis_client.getdel(key) if hasattr(redis_client, "getdel") else None
    if tenant_raw is None and not hasattr(redis_client, "getdel"):
        # Fallback for older redis-py: GET + DELETE (best-effort single-use).
        tenant_raw = redis_client.get(key)
        redis_client.delete(key)
    if tenant_raw is None:
        return None
    return tenant_raw.decode("utf-8") if isinstance(tenant_raw, bytes) else str(tenant_raw)