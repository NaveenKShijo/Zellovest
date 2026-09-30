"""JWT token utilities for authentication and authorization.

``python-jose`` is imported lazily so the package stays importable in
environments where only a subset of extras is installed (e.g. workers).
Service Docker images install ``python-jose`` via their pyproject.
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from pydantic import BaseModel

from zellovest_shared.config import get_settings


def _jose() -> Any:
    """Import python-jose on demand with a clear error if missing."""
    try:
        from jose import jwt
    except ImportError as exc:
        raise ImportError(
            "python-jose is required for JWT operations; "
            "install it with: pip install 'python-jose[cryptography]'"
        ) from exc
    return jwt


class TokenPayload(BaseModel):
    """JWT token payload structure."""

    sub: str  # tenant_id
    role: str = "user"
    exp: int
    iat: int
    jti: str


def create_access_token(
    tenant_id: str,
    role: str = "user",
    expires_delta: timedelta | None = None,
) -> str:
    """Create a JWT access token."""
    settings = get_settings()
    now = datetime.now(UTC)
    expire = now + (expires_delta or timedelta(minutes=settings.jwt_expire_minutes))
    payload = TokenPayload(
        sub=tenant_id,
        role=role,
        exp=int(expire.timestamp()),
        iat=int(now.timestamp()),
        jti=uuid.uuid4().hex,
    )
    return _jose().encode(
        payload.model_dump(),
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )


def decode_token(token: str) -> TokenPayload | None:
    """Decode and validate a JWT token."""
    settings = get_settings()
    try:
        payload = _jose().decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
        )
        return TokenPayload(**payload)
    except Exception:
        return None


def get_tenant_id_from_token(token: str) -> str | None:
    """Extract tenant_id from a JWT token without full validation."""
    try:
        payload = _jose().get_unverified_claims(token)
        return payload.get("sub")
    except Exception:
        return None