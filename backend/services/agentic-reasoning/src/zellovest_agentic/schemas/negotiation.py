"""Negotiation schemas."""

from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field


class NegotiationBriefRequest(BaseModel):
    """Request to prepare a negotiation brief."""

    tenant_id: str = Field(..., min_length=1, max_length=128)
    vendor_id: str = Field(..., min_length=1)
    contract_id: str | None = None
    renewal_date: datetime | None = None
    objectives: list[str] = Field(default_factory=list)


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
    generated_at: datetime


class RenewalPreparationRequest(BaseModel):
    """Request to prepare for renewal."""

    tenant_id: str = Field(..., min_length=1, max_length=128)
    vendor_id: str = Field(..., min_length=1)
    contract_id: str | None = None


class RenewalPreparationResponse(BaseModel):
    """Renewal preparation response."""

    vendor_id: str
    vendor_name: str
    current_annual_spend: Decimal
    renewal_date: datetime
    notice_period_days: int
    auto_renewal: bool
    utilization_rate: float
    unused_licenses: int
    potential_savings: Decimal
    contract_constraints: list[str]
    negotiation_levers: list[str]
    generated_at: datetime