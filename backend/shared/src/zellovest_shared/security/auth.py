"""Shared helpers for custom local authentication (replaces WSO2).

Educational flow overview (email + password + JWT):

1. Signup: validate email shape, enforce min password length, normalize
   email to lowercase, bcrypt-hash the password, insert a ``users`` row.
2. Login: look up by normalized email, bcrypt-verify, return 401 with an
   identical message for "unknown email" vs "wrong password" (no user
   enumeration). On success sign a short-lived HS256 JWT.
3. Authenticated requests: ``Authorization: Bearer <jwt>`` → verify
   signature + expiry → load the user row (revokes deleted/deactivated
   users even before token expiry).

Tenant scoping (V1): single-tenant deployment, so every user belongs to
the instance's fixed tenant (``"default"`` unless overridden). The claim
is reserved for the future multi-org path — never trust a client-supplied
tenant id.
"""

import hashlib
import re
import secrets
from typing import Any

from sqlalchemy import select

from zellovest_shared.db.models import Invitation, User

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MIN_PASSWORD_LENGTH = 8
INVITE_TOKEN_BYTES = 32
DEFAULT_INVITE_TTL_DAYS = 7


def normalize_email(email: str) -> str:
    """Normalize an email for storage/lookup (trim + lowercase)."""
    return email.strip().lower()


def validate_email(email: str) -> bool:
    """Return True for a syntactically plausible email address."""
    return bool(_EMAIL_RE.match(email.strip()))


def validate_password(password: str) -> str | None:
    """Validate password strength; return an error message or None when OK.

    V1 rule is deliberately simple (length >= 8) so the logic stays
    readable; strengthen (classes, breach lists, zxcvbn) per policy.
    """
    if len(password) < MIN_PASSWORD_LENGTH:
        return f"Password must be at least {MIN_PASSWORD_LENGTH} characters."
    return None


async def get_user_by_email(session: Any, email: str) -> User | None:
    """Fetch an active user row by normalized email."""
    result = await session.execute(select(User).where(User.email == normalize_email(email)))
    return result.scalars().first()


async def get_user_by_id(session: Any, user_id: str) -> User | None:
    """Fetch a user row by primary key (string UUID accepted)."""
    try:
        result = await session.execute(select(User).where(User.id == user_id))  # type: ignore[comparison-overlap]
    except Exception:
        return None
    return result.scalars().first()


async def create_user(
    session: Any,
    email: str,
    password: str,
    name: str = "",
    tenant_id: str = "default",
) -> User:
    """Validate, hash, and persist a new user row (shared by seed + invites).

    Args:
        session: Async SQLAlchemy session (caller commits).
        email: Raw email (normalized here).
        password: Plaintext password (validated + PBKDF2-hashed here).
        name: Display name.
        tenant_id: Single-tenant deployment id.

    Raises:
        ValueError: On invalid email, weak password, or duplicate email.
    """
    from zellovest_shared.security.passwords import hash_password

    email = normalize_email(email)
    if not validate_email(email):
        raise ValueError("Invalid email address.")
    if (pw_error := validate_password(password)) is not None:
        raise ValueError(pw_error)
    if await get_user_by_email(session, email) is not None:
        raise ValueError("An account with this email already exists.")
    user = User(
        email=email,
        name=name.strip(),
        password_hash=hash_password(password),
        role="procurement_member",
        tenant_id=tenant_id,
        is_active=True,
    )
    session.add(user)
    return user


def generate_invite_token() -> str:
    """Generate a 256-bit URL-safe invite token (unguessable, single-use).

    ``secrets`` uses the OS CSPRNG — unlike ``random`` or timestamps,
    outputs cannot be predicted even after seeing many tokens.
    """
    return secrets.token_urlsafe(INVITE_TOKEN_BYTES)


def hash_invite_token(raw_token: str) -> str:
    """SHA-256 hash of an invite token for DB storage.

    Only the hash is stored: a database leak does not yield usable invite
    links. The raw token is shown to the inviter exactly once.
    """
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


async def get_invite_by_token(session: Any, raw_token: str) -> Invitation | None:
    """Fetch an invitation row by its raw token (hashed before lookup)."""
    digest = hash_invite_token(raw_token)
    result = await session.execute(select(Invitation).where(Invitation.token_hash == digest))
    return result.scalars().first()
