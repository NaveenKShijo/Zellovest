"""Purchase Order management router."""

from datetime import UTC, datetime
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from zellovest_procurement.api.deps import get_db_session
from zellovest_procurement.schemas.purchase_orders import (
    PurchaseOrderCreate,
    PurchaseOrderListResponse,
    PurchaseOrderResponse,
    PurchaseOrderUpdate,
)
from zellovest_shared.logging_conf import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/purchase-orders", tags=["purchase_orders"])


@router.post("", response_model=PurchaseOrderResponse, status_code=status.HTTP_201_CREATED)
async def create_purchase_order(
    body: PurchaseOrderCreate,
    session: AsyncSession = Depends(get_db_session),
) -> PurchaseOrderResponse:
    """Create a new purchase order (manual entry)."""
    logger.info("po_created", tenant_id=body.tenant_id, vendor_id=body.vendor_id)
    now = datetime.now(UTC)
    return PurchaseOrderResponse(
        id=uuid4(),
        tenant_id=body.tenant_id,
        vendor_id=body.vendor_id,
        po_number=body.po_number,
        order_date=body.order_date,
        expected_date=body.expected_date,
        currency=body.currency,
        line_items=body.line_items,
        subtotal=body.subtotal,
        tax_amount=body.tax_amount,
        total_amount=body.total_amount,
        status=body.status,
        metadata=body.metadata,
        created_at=now,
        updated_at=now,
    )


@router.get("", response_model=PurchaseOrderListResponse)
async def list_purchase_orders(
    tenant_id: str = Query(..., min_length=1),
    vendor_id: str | None = Query(default=None),
    status: str | None = Query(default=None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    session: AsyncSession = Depends(get_db_session),
) -> PurchaseOrderListResponse:
    """List purchase orders with filtering and pagination."""
    logger.info("pos_listed", tenant_id=tenant_id)
    return PurchaseOrderListResponse(
        purchase_orders=[],
        total=0,
        page=page,
        page_size=page_size,
    )


@router.get("/{po_id}", response_model=PurchaseOrderResponse)
async def get_purchase_order(
    po_id: str,
    tenant_id: str = Query(..., min_length=1),
    session: AsyncSession = Depends(get_db_session),
) -> PurchaseOrderResponse:
    """Get a specific purchase order."""
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"Purchase Order {po_id} not found",
    )


@router.patch("/{po_id}", response_model=PurchaseOrderResponse)
async def update_purchase_order(
    po_id: str,
    body: PurchaseOrderUpdate,
    tenant_id: str = Query(..., min_length=1),
    session: AsyncSession = Depends(get_db_session),
) -> PurchaseOrderResponse:
    """Update purchase order information."""
    logger.info("po_updated", po_id=po_id, tenant_id=tenant_id)
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"Purchase Order {po_id} not found",
    )


@router.delete("/{po_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_purchase_order(
    po_id: str,
    tenant_id: str = Query(..., min_length=1),
    session: AsyncSession = Depends(get_db_session),
) -> None:
    """Delete a purchase order."""
    logger.info("po_deleted", po_id=po_id, tenant_id=tenant_id)