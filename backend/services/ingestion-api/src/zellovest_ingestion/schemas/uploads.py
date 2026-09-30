"""Upload schemas."""

from datetime import datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel


class UploadStatus(str, Enum):
    """Upload processing status."""

    STAGED = "staged"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class UploadCreate(BaseModel):
    """Request to create an upload (internal)."""

    tenant_id: str
    filename: str
    document_type: str
    s3_key: str
    file_size: int
    mime_type: str


class UploadResponse(BaseModel):
    """Upload information response."""

    id: UUID
    tenant_id: str
    filename: str
    document_type: str
    status: UploadStatus
    s3_key: str
    file_size: int
    mime_type: str
    error: str | None = None
    created_at: datetime
    updated_at: datetime
    processed_at: datetime | None = None


class UploadListResponse(BaseModel):
    """Paginated upload list."""

    uploads: list[UploadResponse]
    total: int
    page: int
    page_size: int