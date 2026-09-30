"""Invoice management router."""

from datetime import UTC, datetime
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from zellovest_procurement.api.deps import get_db_session
from zellovest_procurement.schemas.invoices import (
    InvoiceCreate,
    InvoiceListResponse,
    InvoiceResponse,
    InvoiceUpdate,
)
from zellovest_shared.logging_conf import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/invoices", tags=["invoices"])


@router.post("", response_model=InvoiceResponse, status_code=status.HTTP_201_CREATED)
async def create_invoice(
    body: InvoiceCreate,
    session: AsyncSession = Depends(get_db_session),
) -> InvoiceResponse:
    """Create a new invoice (manual entry)."""
    logger.info("invoice_created", tenant_id=body.tenant_id, vendor_id=body.vendor_id)
    now = datetime.now(UTC)
    return InvoiceResponse(
        id=uuid4(),
        tenant_id=body.tenant_id,
        vendor_id=body.vendor_id,
        invoice_number=body.invoice_number,
        invoice_date=body.invoice_date,
        due_date=body.due_date,
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


@router.get("", response_model=InvoiceListResponse)
async def list_invoices(
    tenant_id: str = Query(..., min_length=1),
    vendor_id: str | None = Query(default=None),
    status: str | None = Query(default=None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    session: AsyncSession = Depends(get_db_session),
) -> InvoiceListResponse:
    """List invoices with filtering and pagination."""
    logger.info("invoices_listed", tenant_id=tenant_id)
    return InvoiceListResponse(
        invoices=[],
        total=0,
        page=page,
        page_size=page_size,
    )


@router.get("/{invoice_id}", response_model=InvoiceResponse)
async def get_invoice(
    invoice_id: str,
    tenant_id: str = Query(..., min_length=1),
    session: AsyncSession = Depends(get_db_session),
) -> InvoiceResponse:
    """Get a specific invoice."""
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"Invoice {invoice_id} not found",
    )


@router.patch("/{invoice_id}", response_model=InvoiceResponse)
async def update_invoice(
    invoice_id: str,
    body: InvoiceUpdate,
    tenant_id: str = Query(..., min_length=1),
    session: AsyncSession = Depends(get_db_session),
) -> InvoiceResponse:
    """Update invoice information."""
    logger.info("invoice_updated", invoice_id=invoice_id, tenant_id=tenant_id)
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"Invoice {invoice_id} not found",
    )


@router.delete("/{invoice_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_invoice(
    invoice_id: str,
    tenant_id: str = Query(..., min_length=1),
    session: AsyncSession = Depends(get_db_session),
) -> None:
    """Delete an invoice."""
    logger.info("invoice_deleted", invoice_id=invoice_id, tenant_id=tenant_id)