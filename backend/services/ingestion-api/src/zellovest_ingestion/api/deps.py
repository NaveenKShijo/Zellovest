"""Shared FastAPI dependencies: settings, DB sessions, Redis client."""

import redis
from fastapi import Request

from zellovest_ingestion.config import IngestionAPISettings, get_ingestion_api_settings
from zellovest_shared.db.session import async_session_scope


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
