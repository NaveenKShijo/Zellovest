"""Upload schemas."""

from datetime import datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class UploadStatus(str, Enum):
    """Upload processing status."""

    PENDING = "pending"
    STAGED = "staged"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class UploadCreate(BaseModel):
    """Request to create an upload (internal)."""

    tenant_id: str
    filename: str
    document_type: str
    gcs_key: str
    size_expected: int = Field(gt=0)
    mime_type: str
    vendor_id: str | None = None


class UploadResponse(BaseModel):
    """Upload information response."""

    id: UUID
    tenant_id: str
    filename: str
    document_type: str
    status: UploadStatus
    gcs_key: str
    size_expected: int
    mime_type: str
    vendor_id: str | None = None
    error: str | None = None
    expires_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class UploadListResponse(BaseModel):
    """Paginated upload list."""

    uploads: list[UploadResponse]
    total: int
    page: int
    page_size: int


# --- Direct-to-GCS init flow (V1) ---

DEFAULT_TENANT_ID = "default_org"

ALLOWED_MIMES_V1: set[str] = {
    "application/pdf",
    "image/tiff",
    "image/tif",
    "image/png",
    "image/jpeg",
    "image/jpg",
}

ALLOWED_DOC_TYPES: set[str] = {
    "contract",
    "amendment",
    "invoice",
    "purchase_order",
    "policy",
    "other",
}


class UploadInitRequest(BaseModel):
    """Request to initialize a direct-to-GCS manual upload (no file bytes)."""

    tenant_id: str = Field(default=DEFAULT_TENANT_ID, min_length=1, max_length=128)
    filename: str = Field(min_length=1, max_length=255)
    mime_type: str = Field(min_length=1, max_length=128)
    size_bytes: int = Field(gt=0)
    document_type: str = Field(default="other", min_length=1, max_length=32)
    vendor_id: str | None = Field(default=None, max_length=128)

    @field_validator("tenant_id")
    @classmethod
    def _validate_single_tenant(cls, value: str) -> str:
        """Enforce single-tenant V1: only the default tenant is accepted."""
        if value != DEFAULT_TENANT_ID:
            raise ValueError(f"tenant_id must be {DEFAULT_TENANT_ID!r} in V1")
        return value

    @field_validator("mime_type")
    @classmethod
    def _validate_mime(cls, value: str) -> str:
        """Normalize MIME to lowercase (allowlist enforced by the router → 415)."""
        return value.strip().lower()

    @field_validator("document_type")
    @classmethod
    def _validate_document_type(cls, value: str) -> str:
        """Normalize document type to lowercase and enforce allowlist."""
        normalized = value.strip().lower()
        if normalized not in ALLOWED_DOC_TYPES:
            raise ValueError(f"document_type {value!r} is not allowed")
        return normalized


class UploadInitResponse(BaseModel):
    """Signed-URL lease for one direct-to-GCS manual upload."""

    upload_id: UUID
    gcs_key: str
    signed_url: str
    expires_at: datetime


class UploadCompleteResponse(BaseModel):
    """Result of completing a manual upload (PUT verified, worker queued)."""

    upload_id: UUID
    gcs_key: str
    status: UploadStatus
    size_actual: int
    task_id: str | None = None
