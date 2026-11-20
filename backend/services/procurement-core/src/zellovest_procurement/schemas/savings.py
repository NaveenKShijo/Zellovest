"""Schemas for the finance-reviewed procurement savings ledger."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field


class OverbillSavingsRequest(BaseModel):
    """Request to register a potential recovery from an AP overbill exception."""

    exception_id: UUID
    notes: str | None = Field(default=None, max_length=2000)


class SeatReductionSavingsRequest(BaseModel):
    """Request to register a potential pre-renewal seat-reduction saving."""

    forecast_id: UUID
    notes: str | None = Field(default=None, max_length=2000)


class MaverickConsolidationSavingsRequest(BaseModel):
    """Request to register an approved-tool consolidation opportunity."""

    alert_id: UUID
    notes: str | None = Field(default=None, max_length=2000)


class SavingsLedgerResponse(BaseModel):
    """One auditable savings entry and its verification state."""

    id: UUID
    tenant_id: str
    vendor_id: UUID | None
    source_type: str
    source_id: UUID
    amount: Decimal
    currency: str
    kind: str
    status: str
    verified_by_user_id: UUID | None
    verified_at: datetime | None
    notes: str | None
    created_at: datetime
    reused: bool = False


class SavingsLedgerListResponse(BaseModel):
    """Ledger items with deterministic totals split by state and kind."""

    items: list[SavingsLedgerResponse]
    verified_hard_cash: Decimal
    verified_avoidance: Decimal
    potential_hard_cash: Decimal
    potential_avoidance: Decimal
