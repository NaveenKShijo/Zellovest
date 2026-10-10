"""Shared FastAPI dependencies: settings, DB sessions, Redis client, auth."""

import redis
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from zellovest_shared.db.models import User
from zellovest_shared.db.session import async_session_scope
from zellovest_shared.security.auth import get_user_by_id
from zellovest_shared.security.jwt import decode_token
from zellovest_ingestion.config import IngestionAPISettings, get_ingestion_api_settings

bearer_scheme = HTTPBearer(auto_error=False)


def get_app_settings(request: Request) -> IngestionAPISettings:
    """Return settings attached to the app state (test-overridable)."""
    settings = getattr(request.app.state, "settings", None)
    return settings if settings is not None else get_ingestion_api_settings()


def get_redis_client(request: Request) -> redis.Redis:
    """Return Redis client attached to the app state (test-overridable)."""
    client = getattr(request.app.state, "redis", None)
    if client is not None:
        return client
    settings = get_app_settings(request)
    return redis.Redis.from_url(settings.redis_url, decode_responses=False)


async def get_db_session(request: Request):
    """Yield an async DB session bound to the configured database."""
    settings = get_app_settings(request)
    async for session in async_session_scope(settings.async_database_url):
        yield session


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    session=Depends(get_db_session),
) -> User:
    """Resolve the Bearer JWT to an active user row (see procurement-core)."""
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
