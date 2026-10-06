"""Sync schemas (pull sync: Ramp + Google Drive; Okta is webhook-only)."""

from typing import Literal

from pydantic import BaseModel, Field


class SyncRequest(BaseModel):
    """Request to trigger a Ramp pull sync.

    Pull sync is supported for Ramp (``card_transactions``, ``bills``) via
    ``POST /api/v1/sync/ramp`` and for Google Drive via
    ``POST /api/v1/sync/google-drive`` (see ``DriveSyncRequest``).
    Okta is webhook-only and has no pull-sync endpoint.
    """

    tenant_id: str = Field(..., min_length=1, max_length=128)
    entity: Literal["card_transactions", "bills"]
    cursor: str | None = None
    date_from: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    date_to: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")


class DriveSyncRequest(BaseModel):
    """Request to trigger a Google Drive pull sync (``changes.list``).

    Cursor resolution: explicit ``cursor`` wins; otherwise the latest SUCCESS
    checkpoint cursor for the ``documents`` entity resumes the stream;
    ``full_sync`` skips the stored cursor so the worker re-seeds
    ``startPageToken``.
    """

    tenant_id: str = Field(..., min_length=1, max_length=128)
    cursor: str | None = Field(
        default=None, description="changes.list pageToken override"
    )
    full_sync: bool = False
    page_size: int = Field(default=100, ge=1, le=1000)


class SyncResponse(BaseModel):
    """Sync response with ticket."""

    sync_id: str
    task_id: str
    status: Literal["PENDING", "RUNNING", "SUCCESS", "FAILED"]
    deduped: bool
