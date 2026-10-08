"""Sync schemas (pull sync: Ramp + Google Drive + Okta batch)."""

from typing import Literal

from pydantic import BaseModel, Field


class SyncRequest(BaseModel):
    """Request to trigger a Ramp pull sync.

    Pull sync is supported for Ramp (``card_transactions``, ``bills``) via
    ``POST /api/v1/sync/ramp`` and for Google Drive via
    ``POST /api/v1/sync/google-drive`` (see ``DriveSyncRequest``), and Okta
    batch pull (``users``, ``apps``, ``logs``) via
    ``POST /api/v1/sync/okta`` (see ``OktaSyncRequest``).
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


class OktaSyncRequest(BaseModel):
    """Request to trigger an Okta batch pull (users / apps / System Log).

    Cursor resolution: explicit ``cursor`` wins; otherwise the latest SUCCESS
    checkpoint cursor for the ``events`` entity resumes the System Log stream.
    ``since``/``until`` bound the ``/logs`` window (ISO-8601); ``users`` and
    ``apps`` ignore them.
    """

    tenant_id: str = Field(..., min_length=1, max_length=128)
    entities: list[Literal["users", "apps", "logs"]] = Field(
        default_factory=lambda: ["users", "apps", "logs"],
        description="Okta collections to pull",
    )
    cursor: str | None = Field(
        default=None, description="System Log `after` cursor override"
    )
    since: str | None = Field(default=None, description="ISO-8601 lower bound for /logs")
    until: str | None = Field(default=None, description="ISO-8601 upper bound for /logs")
    page_size: int = Field(default=200, ge=1, le=200)
