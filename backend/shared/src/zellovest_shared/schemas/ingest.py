"""Ingestion API request/response schemas."""

from typing import Literal

from pydantic import BaseModel, Field


class SyncRequest(BaseModel):
    """Request to trigger a manual/scheduled sync."""

    tenant_id: str = Field(..., min_length=1, max_length=128)
    entity: Literal["card_transactions", "bills", "invoices", "contracts", "documents"]
    cursor: str | None = None
    date_from: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    date_to: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")


class SyncResponse(BaseModel):
    """Response with sync ticket metadata."""

    sync_id: str
    task_id: str
    status: Literal["PENDING", "RUNNING", "SUCCESS", "FAILED"]
    deduped: bool