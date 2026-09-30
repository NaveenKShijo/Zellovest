"""Purchase Order schemas."""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field


class PurchaseOrderLineItem(BaseModel):
    """PO line item."""

    description: str
    quantity: Decimal
    unit_price: Decimal
    total: Decimal
    product_code: str | None = None


class PurchaseOrderCreate(BaseModel):
    """Request to create a new purchase order."""

    tenant_id: str = Field(..., min_length=1, max_length=128)
    vendor_id: str = Field(..., min_length=1)
    po_number: str = Field(..., min_length=1, max_length=128)
    order_date: datetime
    expected_date: datetime | None = None
    currency: str = Field(default="USD", min_length=3, max_length=3)
    line_items: list[PurchaseOrderLineItem]
    subtotal: Decimal
    tax_amount: Decimal = Field(default=Decimal("0"))
    total_amount: Decimal
    status: str = Field(default="draft")
    metadata: dict | None = None


class PurchaseOrderUpdate(BaseModel):
    """Request to update PO information."""

    po_number: str | None = Field(default=None, min_length=1, max_length=128)
    order_date: datetime | None = None
    expected_date: datetime | None = None
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    line_items: list[PurchaseOrderLineItem] | None = None
    subtotal: Decimal | None = None
    tax_amount: Decimal | None = None
    total_amount: Decimal | None = None
    status: str | None = None
    metadata: dict | None = None


class PurchaseOrderResponse(BaseModel):
    """PO information response."""

    id: UUID
    tenant_id: str
    vendor_id: str
    po_number: str
    order_date: datetime
    expected_date: datetime | None
    currency: str
    line_items: list[PurchaseOrderLineItem]
    subtotal: Decimal
    tax_amount: Decimal
    total_amount: Decimal
    status: str
    metadata: dict | None
    created_at: datetime
    updated_at: datetime


class PurchaseOrderListResponse(BaseModel):
    """Paginated PO list response."""

    purchase_orders: list[PurchaseOrderResponse]
    total: int
    page: int
    page_size: int