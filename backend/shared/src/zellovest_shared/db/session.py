"""Database session management for async and sync contexts."""

from contextlib import asynccontextmanager, contextmanager
from typing import AsyncGenerator, Generator

from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session, sessionmaker

from zellovest_shared.config import get_settings


# Sync engine/session (for Celery workers, Alembic)
_sync_engine = None
_sync_session_factory = None


# Async engine/session (for FastAPI services)
_async_engine = None
_async_session_factory = None


def get_sync_engine():
    """Get or create the sync database engine."""
    global _sync_engine
    if _sync_engine is None:
        settings = get_settings()
        _sync_engine = create_engine(
            settings.database_url,
            pool_pre_ping=True,
            pool_size=5,
            max_overflow=10,
        )
    return _sync_engine


def get_async_engine():
    """Get or create the async database engine."""
    global _async_engine
    if _async_engine is None:
        settings = get_settings()
        _async_engine = create_async_engine(
            settings.async_database_url,
            pool_pre_ping=True,
            pool_size=5,
            max_overflow=10,
        )
    return _async_engine


def get_session_factory():
    """Get the sync session factory."""
    global _sync_session_factory
    if _sync_session_factory is None:
        _sync_session_factory = sessionmaker(
            bind=get_sync_engine(),
            class_=Session,
            expire_on_commit=False,
        )
    return _sync_session_factory


def get_async_session_factory():
    """Get the async session factory."""
    global _async_session_factory
    if _async_session_factory is None:
        _async_session_factory = async_sessionmaker(
            bind=get_async_engine(),
            class_=AsyncSession,
            expire_on_commit=False,
        )
    return _async_session_factory


def get_db_session() -> Generator[Session, None, None]:
    """FastAPI dependency for sync database session."""
    factory = get_session_factory()
    session = factory()
    try:
        yield session
    finally:
        session.close()


async def get_async_db_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency for async database session."""
    factory = get_async_session_factory()
    async with factory() as session:
        yield session


@asynccontextmanager
async def async_session_context() -> AsyncGenerator[AsyncSession, None]:
    """Context manager for async session outside of FastAPI."""
    factory = get_async_session_factory()
    async with factory() as session:
        yield session


@contextmanager
def sync_session_scope(database_url: str) -> Generator[Session, None, None]:
    """Yield a sync session bound to an explicit database URL (worker usage).

    Commits on success, rolls back on error.
    """
    from sqlalchemy import create_engine as _create_engine
    from sqlalchemy.orm import sessionmaker as _sessionmaker

    engine = _create_engine(database_url, pool_pre_ping=True, future=True)
    factory = _sessionmaker(bind=engine, class_=Session, expire_on_commit=False)
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


async def async_session_scope(async_database_url: str) -> AsyncGenerator[AsyncSession, None]:
    """Yield an async session bound to an explicit database URL (API DI usage).

    Commits on success, rolls back on error.
    """
    from sqlalchemy.ext.asyncio import async_sessionmaker as _async_sessionmaker
    from sqlalchemy.ext.asyncio import create_async_engine as _create_async_engine

    engine = _create_async_engine(async_database_url, pool_pre_ping=True, future=True)
    factory = _async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise