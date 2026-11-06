"""FastAPI dependencies for Agentic Reasoning Service."""

import uuid

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from zellovest_shared.db.models import User
from zellovest_shared.security.jwt import decode_token

from zellovest_shared.db.session import get_async_db_session

_bearer = HTTPBearer(auto_error=False)


async def get_db_session() -> AsyncSession:
    """Dependency for async database session."""
    async for session in get_async_db_session():
        yield session


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
    if user is None or user.tenant_id != claims.tenant_id:
        raise HTTPException(status_code=401, detail="invalid access token")
    return user
