"""Database package exports."""

from zellovest_shared.db.base import Base
from zellovest_shared.db.models import (
    ConnectionStatus,
    EntityType,
    IngestionSyncCheckpoint,
    SyncMode,
    SyncStatus,
    TenantIntegration,
)
from zellovest_shared.db.repository import (
    acreate_pending_checkpoint,
    amark_checkpoint,
    aupsert_integration,
    mark_checkpoint,
    upsert_integration_sync,
)
from zellovest_shared.db.session import (
    async_session_scope,
    get_async_db_session,
    get_async_session_factory,
    get_db_session,
    get_session_factory,
    sync_session_scope,
)

__all__ = [
    "Base",
    "TenantIntegration",
    "IngestionSyncCheckpoint",
    "ConnectionStatus",
    "SyncStatus",
    "EntityType",
    "SyncMode",
    "upsert_integration_sync",
    "aupsert_integration",
    "acreate_pending_checkpoint",
    "mark_checkpoint",
    "amark_checkpoint",
    "get_db_session",
    "get_async_db_session",
    "get_session_factory",
    "get_async_session_factory",
    "async_session_scope",
    "sync_session_scope",
]