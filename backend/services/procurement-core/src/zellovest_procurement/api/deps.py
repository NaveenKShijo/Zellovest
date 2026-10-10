"""FastAPI dependencies for Procurement Core Service."""

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from zellovest_shared.db.models import User
from zellovest_shared.db.session import get_async_db_session
from zellovest_shared.security.auth import get_user_by_id
from zellovest_shared.security.jwt import decode_token

bearer_scheme = HTTPBearer(auto_error=False)


async def get_db_session() -> AsyncSession:
    """Dependency for async database session."""
    async for session in get_async_db_session():
        yield session


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    session: AsyncSession = Depends(get_db_session),
) -> User:
    """Resolve the Bearer JWT to an active user row.

    Verifies signature + expiry via ``decode_token``, then loads the user
    (so deactivated/deleted accounts lose access before token expiry).
    Legacy tenant-scoped service tokens (no ``user_id`` claim) are
    rejected here — service-to-service auth stays on its own path.
    """
    if credentials is None or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated."
        )
    payload = decode_token(credentials.credentials)
    user_id = (payload.user_id or payload.sub) if payload else None
    if payload is None or not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token."
        )
    user = await get_user_by_id(session, user_id)
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token."
        )
    return user
