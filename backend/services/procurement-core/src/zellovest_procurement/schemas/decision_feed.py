"""Schemas for the unified in-app Decision Feed and pre-computed packets."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class DecisionPacketItem(BaseModel):
    """One pre-computed, evidence-backed decision card."""

    id: UUID
    tenant_id: str
    packet_type: str
    entity_type: str
    entity_id: UUID
    vendor_id: UUID | None = None
    title: str
    summary: str
    recommended_action: str | None = None
    financial_impact: float | None = None
    currency: str = "USD"
    urgency_date: date | None = None
    source_hash: str
    payload: dict[str, Any] = Field(default_factory=dict)
    status: str
    actioned_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class DecisionFeedSummary(BaseModel):
    """Operational counts and financial exposure for the briefing header."""

    pending_count: int
    total_financial_impact: float
    ap_count: int
    renewal_count: int
    maverick_count: int
    documents_review_needed: int
    unreconciled_invoices_count: int
    active_workflows_count: int
    potential_savings_total: float
    last_sync_at: datetime | None = None


class DecisionFeedResponse(BaseModel):
    """Prioritized decision feed response."""

    items: list[DecisionPacketItem]
    summary: DecisionFeedSummary


class DecisionPacketActionRequest(BaseModel):
    """In-app decision action payload (no external notifications)."""

    action: str = Field(
        ...,
        description="acknowledge | resolve | dismiss | mark_migrated | create_workflow",
    )
    notes: str | None = Field(default=None, max_length=2000)


class DecisionPacketActionResponse(BaseModel):
    """Result of executing an in-app decision packet action."""

    packet: DecisionPacketItem
    workflow_id: UUID | None = None
    savings_entry_id: UUID | None = None
    message: str


class DecisionFeedRefreshResponse(BaseModel):
    """Summary returned after refreshing pre-computed packets."""

    tenant_id: str
    ap_investigation: int
    renewal_dossier: int
    maverick_review: int
