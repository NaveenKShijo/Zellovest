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


