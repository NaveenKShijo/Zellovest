"""Cloud Drive Connectors router."""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from zellovest_ingestion.api.deps import get_db_session
from zellovest_ingestion.schemas.connectors import (
    ConnectorCreate,
    ConnectorListResponse,
    ConnectorResponse,
    ConnectorSyncRequest,
    ConnectorSyncResponse,
    ConnectorType,
)
from zellovest_ingestion.services.connector_manager import ConnectorManager
from zellovest_shared.logging_conf import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/connectors", tags=["connectors"])


@router.post("", response_model=ConnectorResponse, status_code=status.HTTP_201_CREATED)
async def create_connector(
    body: ConnectorCreate,
    session: AsyncSession = Depends(get_db_session),
) -> ConnectorResponse:
    """Register a new cloud drive connector."""
    manager = ConnectorManager(session)
    connector = await manager.create_connector(body)
    logger.info("connector_created", tenant_id=body.tenant_id, type=body.connector_type.value)
    return connector


@router.get("", response_model=ConnectorListResponse)
async def list_connectors(
    tenant_id: str = Query(..., min_length=1),
    connector_type: ConnectorType | None = Query(default=None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    session: AsyncSession = Depends(get_db_session),
) -> ConnectorListResponse:
    """List connectors for a tenant."""
    manager = ConnectorManager(session)
    return await manager.list_connectors(tenant_id, connector_type, page, page_size)


@router.get("/{connector_id}", response_model=ConnectorResponse)
async def get_connector(
    connector_id: str,
    tenant_id: str = Query(..., min_length=1),
    session: AsyncSession = Depends(get_db_session),
) -> ConnectorResponse:
    """Get a specific connector."""
    manager = ConnectorManager(session)
    connector = await manager.get_connector(connector_id, tenant_id)
    if not connector:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Connector {connector_id} not found",
        )
    return connector


@router.post("/{connector_id}/sync", response_model=ConnectorSyncResponse)
async def sync_connector(
    connector_id: str,
    body: ConnectorSyncRequest,
    tenant_id: str = Query(..., min_length=1),
    session: AsyncSession = Depends(get_db_session),
) -> ConnectorSyncResponse:
    """Trigger a sync for a connector."""
    manager = ConnectorManager(session)
    result = await manager.sync_connector(connector_id, tenant_id, body)
    logger.info("connector_sync_triggered", connector_id=connector_id, tenant_id=tenant_id)
    return result


@router.delete("/{connector_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_connector(
    connector_id: str,
    tenant_id: str = Query(..., min_length=1),
    session: AsyncSession = Depends(get_db_session),
) -> None:
    """Delete a connector."""
    manager = ConnectorManager(session)
    await manager.delete_connector(connector_id, tenant_id)
    logger.info("connector_deleted", connector_id=connector_id, tenant_id=tenant_id)


@router.get("/{connector_id}/files")
async def list_connector_files(
    connector_id: str,
    tenant_id: str = Query(..., min_length=1),
    folder_path: str = Query(default="/"),
    session: AsyncSession = Depends(get_db_session),
) -> list[dict]:
    """List files in a cloud drive folder."""
    manager = ConnectorManager(session)
    return await manager.list_files(connector_id, tenant_id, folder_path)