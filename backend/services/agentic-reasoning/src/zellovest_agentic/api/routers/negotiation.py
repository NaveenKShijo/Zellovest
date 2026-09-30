"""Negotiation Copilot Agent router."""

from datetime import UTC, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from zellovest_agentic.api.deps import get_db_session
from zellovest_agentic.schemas.negotiation import (
    NegotiationBriefRequest,
    NegotiationBriefResponse,
    RenewalPreparationRequest,
    RenewalPreparationResponse,
)
from zellovest_shared.logging_conf import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/negotiation", tags=["negotiation"])


@router.post("/brief", response_model=NegotiationBriefResponse)
async def prepare_negotiation_brief(
    body: NegotiationBriefRequest,
    session: AsyncSession = Depends(get_db_session),
) -> NegotiationBriefResponse:
    """Prepare a negotiation brief for a vendor renewal."""
    logger.info("negotiation_brief_requested", tenant_id=body.tenant_id, vendor_id=body.vendor_id)
    
    # TODO: Implement actual negotiation brief generation using MCP tools
    return NegotiationBriefResponse(
        vendor_id=body.vendor_id,
        vendor_name="Unknown Vendor",
        current_spend=Decimal("0"),
        contract_terms={},
        utilization_data={},
        leverage_points=["Placeholder - implement MCP tool calls"],
        recommended_actions=["Placeholder - implement MCP tool calls"],
        talking_points=["Placeholder - implement MCP tool calls"],
        risk_factors=["Placeholder - implement MCP tool calls"],
        generated_at=datetime.now(UTC),
    )


@router.post("/renewal-prep", response_model=RenewalPreparationResponse)
async def prepare_renewal(
    body: RenewalPreparationRequest,
    session: AsyncSession = Depends(get_db_session),
) -> RenewalPreparationResponse:
    """Prepare for a vendor contract renewal."""
    logger.info("renewal_prep_requested", tenant_id=body.tenant_id, vendor_id=body.vendor_id)
    
    return RenewalPreparationResponse(
        vendor_id=body.vendor_id,
        vendor_name="Unknown Vendor",
        current_annual_spend=Decimal("0"),
        renewal_date=datetime.now(UTC),
        notice_period_days=90,
        auto_renewal=False,
        utilization_rate=0.0,
        unused_licenses=0,
        potential_savings=Decimal("0"),
        contract_constraints=["Placeholder - implement MCP tool calls"],
        negotiation_levers=["Placeholder - implement MCP tool calls"],
        generated_at=datetime.now(UTC),
    )


@router.get("/upcoming-renewals")
async def list_upcoming_renewals(
    tenant_id: str = Query(..., min_length=1),
    days_ahead: int = Query(default=90, ge=1, le=365),
    session: AsyncSession = Depends(get_db_session),
) -> list[dict]:
    """List upcoming contract renewals."""
    logger.info("upcoming_renewals_listed", tenant_id=tenant_id, days_ahead=days_ahead)
    return []