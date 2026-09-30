"""FastAPI dependencies for Agentic Reasoning Service."""

from sqlalchemy.ext.asyncio import AsyncSession

from zellovest_shared.db.session import get_async_db_session


async def get_db_session() -> AsyncSession:
    """Dependency for async database session."""
    async for session in get_async_db_session():
        yield session