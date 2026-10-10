"""JWT token utilities for authentication and authorization.

Custom local auth (replaces WSO2/Asgardeo hosted login):

- Access token = signed JSON (header.payload.signature, HS256). The
  server signs with ``JWT_SECRET_KEY``; anyone holding the secret can
  verify. No session table lookup per request (stateless), expiry is
  enforced via the ``exp`` claim.
- ``sub`` carries the user id; ``tenant_id``/``email`` travel as extra
  claims so single-tenant scoping keeps working. Legacy service tokens
  with ``sub=<tenant_id>`` and no ``user_id`` still decode (back-compat).
- Refresh/rotation and revocation lists are intentionally out of scope
  for V1 (short-lived access tokens + password change invalidates on
  next login); add a ``jti`` denylist in Redis when needed.

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

    sub: str  # user_id for user tokens; tenant_id for legacy service tokens
    role: str = "user"
    exp: int
    iat: int
    jti: str
    # User-token claims (absent on legacy tenant-scoped service tokens).
    user_id: str | None = None
    tenant_id: str | None = None
    email: str | None = None


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


def create_user_access_token(
    user_id: str,
    email: str,
    tenant_id: str = "default",
    role: str = "procurement_member",
    expires_delta: timedelta | None = None,
) -> str:
    """Create a JWT access token for a locally authenticated user.

    Args:
        user_id: Primary key of the user row (goes in ``sub``).
        email: User email (display + audit claim).
        tenant_id: Single-tenant deployment id (V1 fixed, reserved).
        role: Single role in V1 (``procurement_member`` for everyone).
        expires_delta: Override for the default ``JWT_EXPIRE_MINUTES``.

    Returns:
        Signed HS256 JWT string.
    """
    settings = get_settings()
    now = datetime.now(UTC)
    expire = now + (expires_delta or timedelta(minutes=settings.jwt_expire_minutes))
    payload = TokenPayload(
        sub=user_id,
        role=role,
        exp=int(expire.timestamp()),
        iat=int(now.timestamp()),
        jti=uuid.uuid4().hex,
        user_id=user_id,
        tenant_id=tenant_id,
        email=email,
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