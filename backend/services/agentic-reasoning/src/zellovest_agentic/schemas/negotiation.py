"""Negotiation schemas for Renewal Intelligence & Negotiation Copilot."""

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field


class NegotiationBriefRequest(BaseModel):
    """Request to prepare a negotiation brief."""

    tenant_id: str | None = Field(default=None, max_length=128)
    vendor_id: str = Field(..., min_length=1)
    contract_id: str | None = None
    renewal_date: datetime | date | None = None
    objectives: list[str] = Field(default_factory=list)


class ClauseCitation(BaseModel):
    """Specific contract clause citation supporting a lever or constraint."""

    clause_type: str
    summary: str
    document_id: str | None = None
    filename: str | None = None
    page: int | None = None
    section: str | None = None
    verbatim_excerpt: str | None = None


class NegotiationBriefResponse(BaseModel):
    """Prepared negotiation brief."""

    vendor_id: str
    vendor_name: str
    current_spend: Decimal
    contract_terms: dict[str, Any]
    utilization_data: dict[str, Any]
    leverage_points: list[str]
    recommended_actions: list[str]
    talking_points: list[str]
    risk_factors: list[str]
    contractual_clauses: list[ClauseCitation] = Field(default_factory=list)
    generated_at: datetime


class RenewalPreparationRequest(BaseModel):
    """Request to prepare for renewal."""

    tenant_id: str | None = Field(default=None, max_length=128)
    vendor_id: str = Field(..., min_length=1)
    contract_id: str | None = None


class RenewalPreparationResponse(BaseModel):
    """Renewal preparation response."""

    vendor_id: str
    vendor_name: str
    current_annual_spend: Decimal
    renewal_date: datetime | date
    notice_period_days: int
    auto_renewal: bool
    utilization_rate: float
    unused_licenses: int
    potential_savings: Decimal
    contract_constraints: list[str]
    negotiation_levers: list[str]
    generated_at: datetime


class UpcomingRenewalResponse(BaseModel):
    """Upcoming renewal countdown card."""

    id: str
    contract_id: str
    contract_number: str
    vendor_id: str
    vendor_name: str
    product_name: str
    annual_spend: float
    spend_yoy_pct: float
    renewal_date: str
    days_until_renewal: int
    badge: str  # '30d' | '60d' | '90d' | '120d' | 'future'
    auto_renew: bool
    notice_period_days: int
    notice_deadline_date: str
    days_until_notice_deadline: int
    is_notice_window_active: bool
    utilization_pct: float
    assigned_owner: str
    status: str
    key_leverage_points: list[str]


class RenewalReminderRequest(BaseModel):
    """Request to set a reminder before the notice deadline."""

    contract_id: str = Field(..., min_length=1)
    vendor_id: str = Field(..., min_length=1)
    remind_days_before_notice: int = Field(default=15, ge=1, le=180)
    notes: str | None = None


class RenewalReminderResponse(BaseModel):
    """Confirmation of a scheduled renewal reminder."""

    reminder_id: str
    contract_id: str
    vendor_name: str
    notice_deadline_date: str
    remind_date: str
    days_until_notice: int
    status: str
    message: str


class RenewalReminderItem(BaseModel):
    """An active reminder entry."""

    id: str
    contract_id: str
    contract_number: str
    vendor_id: str
    vendor_name: str
    notice_deadline_date: str
    remind_date: str
    days_until_notice: int
    status: str
    notes: str | None = None
    created_at: str
