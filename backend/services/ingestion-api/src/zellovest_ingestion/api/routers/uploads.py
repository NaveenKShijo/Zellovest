"""File Upload Staging router."""

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from zellovest_ingestion.api.deps import get_db_session
from zellovest_ingestion.schemas.uploads import (
    UploadListResponse,
    UploadResponse,
    UploadStatus,
)
from zellovest_ingestion.services.upload_manager import UploadManager
from zellovest_shared.logging_conf import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/uploads", tags=["uploads"])


@router.post("", response_model=UploadResponse, status_code=status.HTTP_201_CREATED)
async def create_upload(
    file: UploadFile = File(...),
    tenant_id: str = Query(..., min_length=1),
    document_type: str = Query(..., pattern="^(contract|invoice|po|policy|other)$"),
    session: AsyncSession = Depends(get_db_session),
) -> UploadResponse:
    """Stage a file for document processing."""
    manager = UploadManager(session)
    upload = await manager.stage_upload(
        tenant_id=tenant_id,
        file=file,
        document_type=document_type,
    )
    logger.info("upload_staged", tenant_id=tenant_id, filename=file.filename)
    return upload


@router.get("", response_model=UploadListResponse)
async def list_uploads(
    tenant_id: str = Query(..., min_length=1),
    status: UploadStatus | None = Query(default=None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    session: AsyncSession = Depends(get_db_session),
) -> UploadListResponse:
    """List staged uploads."""
    manager = UploadManager(session)
    return await manager.list_uploads(tenant_id, status, page, page_size)


@router.get("/{upload_id}", response_model=UploadResponse)
async def get_upload(
    upload_id: str,
    tenant_id: str = Query(..., min_length=1),
    session: AsyncSession = Depends(get_db_session),
) -> UploadResponse:
    """Get upload status."""
    manager = UploadManager(session)
    upload = await manager.get_upload(upload_id, tenant_id)
    if not upload:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Upload {upload_id} not found",
        )
    return upload


@router.post("/{upload_id}/process", response_model=UploadResponse)
async def process_upload(
    upload_id: str,
    tenant_id: str = Query(..., min_length=1),
    session: AsyncSession = Depends(get_db_session),
) -> UploadResponse:
    """Trigger document processing for an uploaded file."""
    manager = UploadManager(session)
    upload = await manager.process_upload(upload_id, tenant_id)
    if not upload:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Upload {upload_id} not found",
        )
    logger.info("upload_processing_triggered", upload_id=upload_id)
    return upload


@router.delete("/{upload_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_upload(
    upload_id: str,
    tenant_id: str = Query(..., min_length=1),
    session: AsyncSession = Depends(get_db_session),
) -> None:
    """Delete a staged upload."""
    manager = UploadManager(session)
    await manager.delete_upload(upload_id, tenant_id)
    logger.info("upload_deleted", upload_id=upload_id)