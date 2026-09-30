"""Connector schemas."""

from datetime import datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, Field


class ConnectorType(str, Enum):
    """Supported connector types."""

    GOOGLE_DRIVE = "google_drive"
    DROPBOX = "dropbox"
    S3 = "s3"
    ONEDRIVE = "onedrive"
    SHAREPOINT = "sharepoint"


class ConnectorStatus(str, Enum):
    """Connector connection status."""

    ACTIVE = "active"
    EXPIRED = "expired"
    ERROR = "error"
    DISCONNECTED = "disconnected"


class ConnectorCreate(BaseModel):
    """Request to create a connector."""

    tenant_id: str = Field(..., min_length=1, max_length=128)
    connector_type: ConnectorType
    name: str = Field(..., min_length=1, max_length=256)
    config: dict  # OAuth tokens, folder paths, etc.
    sync_schedule: str | None = None  # Cron expression


class ConnectorUpdate(BaseModel):
    """Request to update a connector."""

    name: str | None = Field(default=None, min_length=1, max_length=256)
    config: dict | None = None
    sync_schedule: str | None = None


class ConnectorResponse(BaseModel):
    """Connector information response."""

    id: UUID
    tenant_id: str
    connector_type: ConnectorType
    name: str
    status: ConnectorStatus
    config: dict
    sync_schedule: str | None
    last_sync_at: datetime | None
    last_error: str | None
    created_at: datetime
    updated_at: datetime


class ConnectorListResponse(BaseModel):
    """Paginated connector list."""

    connectors: list[ConnectorResponse]
    total: int
    page: int
    page_size: int


class ConnectorSyncRequest(BaseModel):
    """Request to trigger a connector sync."""

    full_sync: bool = False
    folder_path: str | None = None


class ConnectorSyncResponse(BaseModel):
    """Connector sync response."""

    sync_id: str
    status: str
    message: str