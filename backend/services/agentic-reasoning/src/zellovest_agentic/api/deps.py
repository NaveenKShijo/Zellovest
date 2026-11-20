"""FastAPI dependencies for Agentic Reasoning Service."""

import uuid

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from zellovest_shared.db.models import User
from zellovest_shared.security.jwt import decode_token

from zellovest_shared.db.session import get_async_db_session

from zellovest_agentic.mcp.client import McpIdentity

_bearer = HTTPBearer(auto_error=False)


async def get_db_session() -> AsyncSession:
    """Dependency for async database session."""
    async for session in get_async_db_session():
        yield session


def normalize_tenant_id(tenant_id: str | None) -> str:
    """Normalize single-tenant deployment ID aliases (default -> default-org)."""
    if tenant_id in (None, "", "default", "default-org"):
        return "default-org"
    return tenant_id


def build_mcp_identity(user: User, request_id: str) -> McpIdentity:
    """Build the MCP identity propagated to the three MCP servers.

    Tenant and actor are derived from the authenticated user, never from tool
    arguments or a client-supplied tenant id (PRD 25.5 tenant boundary).

    Args:
        user: Authenticated database user.
        request_id: Correlation id assigned by request middleware.

    Returns:
        Immutable identity carried in MCP transport headers.
    """
    tenant_id = normalize_tenant_id(user.tenant_id)
    return McpIdentity(
        tenant_id=tenant_id,
        actor_id=str(user.id),
        role=user.role or "procurement_member",
        correlation_id=request_id,
        deployment_id=tenant_id,
        actor_email=user.email,
    )


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    session: AsyncSession = Depends(get_db_session),
) -> User:
    """Validate a user access token and return its active database user."""
    if credentials is None:
        raise HTTPException(status_code=401, detail="authentication required")
    claims = decode_token(credentials.credentials)
    if claims is None or claims.token_type != "access" or not claims.user_id:
        raise HTTPException(status_code=401, detail="invalid access token")
    try:
        user_id = uuid.UUID(claims.user_id)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="invalid access token") from exc
    user = await session.scalar(select(User).where(User.id == user_id, User.is_active.is_(True)))
    if user is None:
        raise HTTPException(status_code=401, detail="invalid access token")
    if normalize_tenant_id(user.tenant_id) != normalize_tenant_id(claims.tenant_id):
        raise HTTPException(status_code=401, detail="invalid access token")
    return user


async def get_optional_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    session: AsyncSession = Depends(get_db_session),
) -> User | None:
    """Validate a user access token if provided, returning None if unauthenticated."""
    if credentials is None or not credentials.credentials:
        return None
    try:
        claims = decode_token(credentials.credentials)
        if claims is None or claims.token_type != "access" or not claims.user_id:
            return None
        user_id = uuid.UUID(claims.user_id)
        user = await session.scalar(select(User).where(User.id == user_id, User.is_active.is_(True)))
        if user is None:
            return None
        if normalize_tenant_id(user.tenant_id) != normalize_tenant_id(claims.tenant_id):
            return None
        return user
    except Exception:
        return None
