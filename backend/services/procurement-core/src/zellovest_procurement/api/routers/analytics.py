"""Spend analytics router."""

from datetime import UTC, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from zellovest_procurement.api.deps import get_db_session
from zellovest_procurement.schemas.analytics import (
    SpendAnalyticsResponse,
    SpendByCategory,
    SpendByVendor,
    SpendTrend,
    VendorSpendDetail,
)
from zellovest_shared.logging_conf import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/spend", response_model=SpendAnalyticsResponse)
async def get_spend_analytics(
    tenant_id: str = Query(..., min_length=1),
    period_start: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    period_end: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    session: AsyncSession = Depends(get_db_session),
) -> SpendAnalyticsResponse:
    """Get aggregated spend analytics for a tenant."""
    logger.info("spend_analytics_requested", tenant_id=tenant_id)
    now = datetime.now(UTC)
    return SpendAnalyticsResponse(
        tenant_id=tenant_id,
        period_start=datetime.fromisoformat(period_start) if period_start else now,
        period_end=datetime.fromisoformat(period_end) if period_end else now,
        total_spend=Decimal("0"),
        by_vendor=[],
        by_category=[],
        trend=[],
        generated_at=now,
    )


@router.get("/spend/vendor/{vendor_id}", response_model=VendorSpendDetail)
async def get_vendor_spend_detail(
    vendor_id: str,
    tenant_id: str = Query(..., min_length=1),
    session: AsyncSession = Depends(get_db_session),
) -> VendorSpendDetail:
    """Get detailed spend analytics for a specific vendor."""
    logger.info("vendor_spend_detail_requested", tenant_id=tenant_id, vendor_id=vendor_id)
    return VendorSpendDetail(
        vendor_id=vendor_id,
        vendor_name="Unknown",
        total_spend=Decimal("0"),
        invoice_count=0,
        contract_count=0,
        avg_invoice_amount=Decimal("0"),
        largest_invoice=Decimal("0"),
        spend_by_category=[],
        trend=[],
    )


@router.get("/spend/trends", response_model=list[SpendTrend])
async def get_spend_trends(
    tenant_id: str = Query(..., min_length=1),
    granularity: str = Query(default="monthly", pattern="^(daily|weekly|monthly|quarterly)$"),
    periods: int = Query(default=12, ge=1, le=36),
    session: AsyncSession = Depends(get_db_session),
) -> list[SpendTrend]:
    """Get spend trends over time."""
    logger.info("spend_trends_requested", tenant_id=tenant_id, granularity=granularity)
    return []


@router.get("/spend/by-category", response_model=list[SpendByCategory])
async def get_spend_by_category(
    tenant_id: str = Query(..., min_length=1),
    session: AsyncSession = Depends(get_db_session),
) -> list[SpendByCategory]:
    """Get spend breakdown by category."""
    logger.info("spend_by_category_requested", tenant_id=tenant_id)
    return []


@router.get("/spend/by-vendor", response_model=list[SpendByVendor])
async def get_spend_by_vendor(
    tenant_id: str = Query(..., min_length=1),
    limit: int = Query(default=20, ge=1, le=100),
    session: AsyncSession = Depends(get_db_session),
) -> list[SpendByVendor]:
    """Get top vendors by spend."""
    logger.info("spend_by_vendor_requested", tenant_id=tenant_id)
    return []