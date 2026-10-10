"""Custom local authentication router on the ingestion gateway.

The frontend proxy (``next.config.ts`` rewrites ``/api/v1/*``) points at
this service, so login/me/invites must be reachable here — the user rows
live in the shared ``users``/``invitations`` tables, identical to
procurement-core. Public signup is removed: accounts are created by the
seed script (first/demo user) or by claiming an invite.
"""

import os
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.security import HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from zellovest_shared.db.models import Invitation, User
from zellovest_shared.logging_conf import get_logger
from zellovest_shared.security.auth import (
    DEFAULT_INVITE_TTL_DAYS,
    create_user,
    generate_invite_token,
    get_invite_by_token,
    get_user_by_email,
    hash_invite_token,
    normalize_email,
    validate_email,
)
from zellovest_shared.security.jwt import create_user_access_token
from zellovest_shared.security.passwords import verify_password
from zellovest_ingestion.api.deps import get_current_user, get_db_session
from zellovest_ingestion.config import get_ingestion_api_settings
from zellovest_ingestion.schemas.auth import (
    AuthResponse,
    InviteAcceptRequest,
    InviteCreateRequest,
    InviteResponse,
    InviteValidateResponse,
    LoginRequest,
    UserResponse,
)

logger = get_logger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])
bearer_scheme = HTTPBearer(auto_error=False)

def _invite_ttl_days() -> int:
    """Invite lifetime in days (env-overridable, safe default of 7)."""
    try:
        return max(1, int(os.environ.get("INVITE_TOKEN_TTL_DAYS", DEFAULT_INVITE_TTL_DAYS)))
    except ValueError:
        return DEFAULT_INVITE_TTL_DAYS


INVITE_TTL_DAYS = _invite_ttl_days()


def _to_user_response(user: User) -> UserResponse:
    """Map a User row to its public profile shape."""
    return UserResponse(
        id=str(user.id),
        email=user.email,
        name=user.name,
        role=user.role,
        tenant_id=user.tenant_id,
    )


def _expiry_minutes() -> int:
    """Read JWT expiry from app settings (defaults to 60)."""
    try:
        return get_ingestion_api_settings().jwt_expire_minutes
    except Exception:
        return 60


def _invite_error() -> HTTPException:
    """Enumeration-safe error for invalid/used/expired invite links."""
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND, detail="This invite link is invalid or expired."
    )


@router.post("/login", response_model=AuthResponse)
async def login(
    body: LoginRequest,
    session: AsyncSession = Depends(get_db_session),
) -> AuthResponse:
    """Authenticate and receive a JWT access token."""
    email = normalize_email(body.email)
    user = await get_user_by_email(session, email)
    password_ok = user is not None and verify_password(body.password, user.password_hash)
    if user is None or not user.is_active or not password_ok:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password."
        )
    logger.info("user_logged_in", email=email)
    token = create_user_access_token(str(user.id), user.email, user.tenant_id, user.role)
    return AuthResponse(
        access_token=token, expires_in_minutes=_expiry_minutes(), user=_to_user_response(user)
    )


@router.get("/me", response_model=UserResponse)
async def me(current_user: User = Depends(get_current_user)) -> UserResponse:
    """Return the profile for the presented Bearer token."""
    return _to_user_response(current_user)


@router.post("/invites", response_model=InviteResponse, status_code=status.HTTP_201_CREATED)
async def create_invite(
    body: InviteCreateRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> InviteResponse:
    """Invite a teammate: any authenticated member may invite (single role)."""
    email = normalize_email(body.email)
    if not validate_email(email):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid email address.",
        )
    if await get_user_by_email(session, email) is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists.",
        )
    now = datetime.now(UTC)
    pending = await session.execute(
        select(Invitation).where(
            Invitation.email == email,
            Invitation.accepted_at.is_(None),
            Invitation.expires_at > now,
        )
    )
    if pending.scalars().first() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A pending invite for this email already exists.",
        )
    raw_token = generate_invite_token()
    invitation = Invitation(
        email=email,
        token_hash=hash_invite_token(raw_token),
        invited_by_user_id=current_user.id,
        tenant_id=current_user.tenant_id,
        expires_at=now + timedelta(days=INVITE_TTL_DAYS),
    )
    session.add(invitation)
    await session.commit()
    logger.info("invite_created", email=email, invited_by=str(current_user.id))
    return InviteResponse(
        email=email,
        invite_token=raw_token,
        expires_at=invitation.expires_at.isoformat(),
    )


@router.get("/invites/validate", response_model=InviteValidateResponse)
async def validate_invite(
    token: str = Query(min_length=16, max_length=128),
    session: AsyncSession = Depends(get_db_session),
) -> InviteValidateResponse:
    """Check an invite link before showing the accept form (public)."""
    invitation = await get_invite_by_token(session, token)
    now = datetime.now(UTC)
    expires_at = invitation.expires_at if invitation else None
    if expires_at is not None and expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    if invitation is None or invitation.accepted_at is not None or expires_at <= now:
        raise _invite_error()
    return InviteValidateResponse(email=invitation.email, expires_at=expires_at.isoformat())


@router.post("/invites/accept", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
async def accept_invite(
    body: InviteAcceptRequest,
    session: AsyncSession = Depends(get_db_session),
) -> AuthResponse:
    """Claim an invitation: creates the user, burns the token, logs in."""
    invitation = await get_invite_by_token(session, body.token)
    now = datetime.now(UTC)
    expires_at = invitation.expires_at if invitation else None
    if expires_at is not None and expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    if invitation is None or invitation.accepted_at is not None or expires_at <= now:
        raise _invite_error()
    try:
        user = await create_user(
            session,
            email=invitation.email,
            password=body.password,
            name=body.name,
            tenant_id=invitation.tenant_id,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    invitation.accepted_at = now
    await session.commit()
    await session.refresh(user)
    logger.info("invite_accepted", email=user.email)
    token = create_user_access_token(str(user.id), user.email, user.tenant_id, user.role)
    return AuthResponse(
        access_token=token, expires_in_minutes=_expiry_minutes(), user=_to_user_response(user)
    )
