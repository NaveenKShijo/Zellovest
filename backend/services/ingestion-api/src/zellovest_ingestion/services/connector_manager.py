"""Cloud drive connector management."""

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from zellovest_ingestion.schemas.connectors import (
    ConnectorCreate,
    ConnectorListResponse,
    ConnectorResponse,
    ConnectorSyncRequest,
    ConnectorSyncResponse,
    ConnectorStatus,
    ConnectorType,
)


class ConnectorManager:
    """Manages cloud drive connectors."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_connector(self, body: ConnectorCreate) -> ConnectorResponse:
        """Create a new connector (mock implementation)."""
        now = datetime.now(UTC)
        return ConnectorResponse(
            id=uuid4(),
            tenant_id=body.tenant_id,
            connector_type=body.connector_type,
            name=body.name,
            status=ConnectorStatus.ACTIVE,
            config=body.config,
            sync_schedule=body.sync_schedule,
            last_sync_at=None,
            last_error=None,
            created_at=now,
            updated_at=now,
        )

    async def list_connectors(
        self,
        tenant_id: str,
        connector_type: ConnectorType | None,
        page: int,
        page_size: int,
    ) -> ConnectorListResponse:
        """List connectors for a tenant (mock)."""
        return ConnectorListResponse(
            connectors=[],
            total=0,
            page=page,
            page_size=page_size,
        )

    async def get_connector(self, connector_id: str, tenant_id: str) -> ConnectorResponse | None:
        """Get a connector by ID (mock)."""
        return None

    async def sync_connector(
        self,
        connector_id: str,
        tenant_id: str,
        body: ConnectorSyncRequest,
    ) -> ConnectorSyncResponse:
        """Trigger a connector sync (mock)."""
        return ConnectorSyncResponse(
            sync_id=str(uuid4()),
            status="accepted",
            message="Sync queued - implement connector-specific sync logic",
        )

    async def delete_connector(self, connector_id: str, tenant_id: str) -> None:
        """Delete a connector (mock)."""
        pass

    async def list_files(self, connector_id: str, tenant_id: str, folder_path: str) -> list[dict]:
        """List files in a cloud drive folder (mock)."""
        return []