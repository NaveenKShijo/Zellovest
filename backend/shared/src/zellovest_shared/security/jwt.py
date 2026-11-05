"""JWT token utilities for authentication and authorization.

Custom local auth (replaces WSO2/Asgardeo hosted login). Implemented on
the standard library only — no third-party JWT package — so every step
is visible (this previously depended on ``python-jose``, which was
missing from service environments and turned every successful login
into a 500; stdlib has no such failure mode).

How an HS256 JWT works (RFC 7519), in full:

1. Take the JSON header ``{"alg":"HS256","typ":"JWT"}`` and the JSON
   payload (claims such as ``sub``, ``exp``, ``iat``, ``jti``).
2. base64url-encode each part (URL-safe alphabet, ``=`` padding stripped)
   and join with dots: ``<header_b64>.<payload_b64>``.
3. Sign those exact bytes: ``HMAC-SHA256(key=JWT_SECRET_KEY, msg=...)``,
   base64url-encode the 32-byte MAC, append as the third segment.

Verification reverses it: split on dots, recompute the MAC over the
*received* first two segments, compare with ``hmac.compare_digest``
(constant time — no timing oracle), parse the payload, and reject when
``exp`` has passed (30s clock-skew leeway). Because verification only
re-signs the received bytes, tokens minted by any spec-compliant
library (e.g. the old python-jose path) keep verifying here.

- ``sub`` carries the user id; ``tenant_id``/``email`` travel as extra
  claims so single-tenant scoping keeps working. Legacy service tokens
  with ``sub=<tenant_id>`` and no ``user_id`` still decode (back-compat).
- Access tokens are short-lived (``JWT_EXPIRE_MINUTES``, default 60).
  Refresh tokens are long-lived (``JWT_REFRESH_EXPIRE_DAYS``, default 7)
  and carry ``token_type="refresh"`` so they can never be mistaken for an
  access token. ``POST /auth/refresh`` exchanges one for a fresh pair.
- Revocation lists remain out of scope for V1 (deactivation is checked
  per request in ``get_current_user``); add a ``jti`` denylist in Redis
  when immediate refresh-token revocation is required.
"""

import base64
import hashlib
import hmac
import json
import os
import time
import uuid
from datetime import UTC, datetime, timedelta

from pydantic import BaseModel

_HEADER = {"alg": "HS256", "typ": "JWT"}
# Clock-skew leeway (seconds) accepted on top of ``exp``.
_EXP_LEEWAY_SECONDS = 30


_DOTENV_LOADED = False


def _ensure_dotenv() -> None:
    """Load ``backend/.env`` into ``os.environ`` once (shell env wins).

    Services are typically started as bare ``uvicorn ...`` with no exported
    variables — nothing puts ``backend/.env`` into the process environment
    (pydantic-settings reads the file internally, which plain ``os.environ``
    lookups never see). Without this, every token operation raises even
    though the secret is sitting in ``.env``. ``override=False`` keeps
    explicitly exported variables authoritative.
    """
    global _DOTENV_LOADED
    if _DOTENV_LOADED:
        return
    try:
        from dotenv import find_dotenv, load_dotenv
    except ImportError:
        return
    found = find_dotenv(usecwd=True)
    if found:
        load_dotenv(found, override=False)
    _DOTENV_LOADED = True


def _jwt_settings() -> tuple[str, str, int]:
    """Read the three JWT knobs straight from the environment.

    Deliberately NOT via the shared ``Settings`` object: that requires
    the full service env (Ramp keys, DB URLs, …), so a deployment missing
    an unrelated variable would 500 every login/token check. The JWT
    layer needs exactly secret + algorithm + lifetime — nothing else.
    """
    _ensure_dotenv()
    secret = os.environ.get("JWT_SECRET_KEY", "")
    if not secret:
        raise RuntimeError("JWT_SECRET_KEY is not set")
    algorithm = os.environ.get("JWT_ALGORITHM", "HS256")
    if algorithm != "HS256":
        raise RuntimeError(f"Unsupported JWT_ALGORITHM {algorithm!r} (only HS256 is implemented)")
    try:
        lifetime = int(os.environ.get("JWT_EXPIRE_MINUTES", "60"))
    except ValueError:
        lifetime = 60
    return secret, algorithm, max(1, lifetime)


def _refresh_lifetime_days() -> int:
    """Read the refresh-token lifetime in days (default 7)."""
    _ensure_dotenv()
    try:
        days = int(os.environ.get("JWT_REFRESH_EXPIRE_DAYS", "7"))
    except ValueError:
        days = 7
    return max(1, days)


def _b64url_encode(raw: bytes) -> str:
    """base64url-encode without padding (RFC 7515 Appendix C)."""
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64url_decode(segment: str) -> bytes:
    """Decode an unpadded base64url segment (raises on malformed input)."""
    padding = "=" * (-len(segment) % 4)
    return base64.urlsafe_b64decode(segment + padding)


def _sign(signing_input: str, secret: str) -> str:
    """Compute the HS256 signature segment for ``header_b64.payload_b64``."""
    mac = hmac.new(secret.encode("utf-8"), signing_input.encode("ascii"), hashlib.sha256)
    return _b64url_encode(mac.digest())


class TokenPayload(BaseModel):
    """JWT token payload structure."""

    sub: str  # user_id for user tokens; tenant_id for legacy service tokens
    role: str = "user"
    exp: int
    iat: int
    jti: str
    token_type: str | None = None  # "access" | "refresh" — distinguishes token kinds
    # User-token claims (absent on legacy tenant-scoped service tokens).
    user_id: str | None = None
    tenant_id: str | None = None
    email: str | None = None


def _encode_payload(
    sub: str,
    role: str,
    expire: datetime,
    now: datetime,
    extra: dict | None = None,
) -> str:
    """Build and sign a token from claims (shared by both issuers)."""
    secret, _algorithm, _lifetime = _jwt_settings()
    payload = TokenPayload(
        sub=sub,
        role=role,
        exp=int(expire.timestamp()),
        iat=int(now.timestamp()),
        jti=uuid.uuid4().hex,
        **(extra or {}),
    )
    header_b64 = _b64url_encode(json.dumps(_HEADER, separators=(",", ":")).encode("utf-8"))
    payload_b64 = _b64url_encode(
        json.dumps(payload.model_dump(exclude_none=True), separators=(",", ":")).encode("utf-8")
    )
    signing_input = f"{header_b64}.{payload_b64}"
    return f"{signing_input}.{_sign(signing_input, secret)}"


def create_access_token(
    tenant_id: str,
    role: str = "user",
    expires_delta: timedelta | None = None,
) -> str:
    """Create a JWT access token (legacy tenant-scoped service token)."""
    _, _, lifetime = _jwt_settings()
    now = datetime.now(UTC)
    expire = now + (expires_delta or timedelta(minutes=lifetime))
    return _encode_payload(tenant_id, role, expire, now)


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
    _, _, lifetime = _jwt_settings()
    now = datetime.now(UTC)
    expire = now + (expires_delta or timedelta(minutes=lifetime))
    return _encode_payload(
        user_id,
        role,
        expire,
        now,
        extra={"user_id": user_id, "tenant_id": tenant_id, "email": email, "token_type": "access"},
    )


def create_refresh_token(
    user_id: str,
    email: str,
    tenant_id: str = "default",
    expires_delta: timedelta | None = None,
) -> str:
    """Create a long-lived JWT refresh token for rotating access tokens.

    A refresh token is a separate HS256 JWT with a much longer default
    lifetime (``JWT_REFRESH_EXPIRE_DAYS``, default 7 days) and a
    ``token_type: "refresh"`` claim so it can never be confused with an
    access token. It is stored client-side (localStorage) and presented to
    ``POST /auth/refresh`` to mint a new access token without re-entering
    credentials.

    Args:
        user_id: Primary key of the user row (goes in ``sub``).
        email: User email (display + audit claim).
        tenant_id: Single-tenant deployment id (V1 fixed, reserved).
        expires_delta: Override for the default refresh lifetime.

    Returns:
        Signed HS256 JWT string.
    """
    _jwt_settings()  # validates that JWT_SECRET_KEY / algorithm are usable
    now = datetime.now(UTC)
    expire = now + (expires_delta or timedelta(days=_refresh_lifetime_days()))
    return _encode_payload(
        user_id,
        "refresh",
        expire,
        now,
        extra={"user_id": user_id, "tenant_id": tenant_id, "email": email, "token_type": "refresh"},
    )


def decode_token(token: str) -> TokenPayload | None:
    """Decode and validate a JWT token (signature + expiry).

    Returns the payload on success, None on any failure (bad shape,
    bad signature, expired, non-JSON payload) — callers treat None as
    "unauthenticated" without distinguishing reasons.
    """
    try:
        header_b64, payload_b64, signature_b64 = token.split(".")
        secret, _algorithm, _lifetime = _jwt_settings()
        expected = _sign(f"{header_b64}.{payload_b64}", secret)
        if not hmac.compare_digest(expected, signature_b64):
            return None
        header = json.loads(_b64url_decode(header_b64))
        if header.get("alg") != "HS256":
            return None
        payload = TokenPayload(**json.loads(_b64url_decode(payload_b64)))
    except Exception:
        return None
    if payload.exp < int(time.time()) - _EXP_LEEWAY_SECONDS:
        return None
    return payload


def get_tenant_id_from_token(token: str) -> str | None:
    """Extract tenant_id from a JWT token without full validation."""
    try:
        payload_b64 = token.split(".")[1]
        claims = json.loads(_b64url_decode(payload_b64))
        return claims.get("tenant_id") or claims.get("sub")
    except Exception:
        return None
