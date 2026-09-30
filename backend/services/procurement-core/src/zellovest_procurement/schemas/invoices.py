"""Invoice schemas."""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field


class InvoiceLineItem(BaseModel):
    """Invoice line item."""

    description: str
    quantity: Decimal
    unit_price: Decimal
    total: Decimal
    product_code: str | None = None


class InvoiceCreate(BaseModel):
    """Request to create a new invoice."""

    tenant_id: str = Field(..., min_length=1, max_length=128)
    vendor_id: str = Field(..., min_length=1)
    invoice_number: str = Field(..., min_length=1, max_length=128)
    invoice_date: datetime
    due_date: datetime | None = None
    currency: str = Field(default="USD", min_length=3, max_length=3)
    line_items: list[InvoiceLineItem]
    subtotal: Decimal
    tax_amount: Decimal = Field(default=Decimal("0"))
    total_amount: Decimal
    status: str = Field(default="pending")
    metadata: dict | None = None


class InvoiceUpdate(BaseModel):
    """Request to update invoice information."""

    invoice_number: str | None = Field(default=None, min_length=1, max_length=128)
    invoice_date: datetime | None = None
    due_date: datetime | None = None
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    line_items: list[InvoiceLineItem] | None = None
    subtotal: Decimal | None = None
    tax_amount: Decimal | None = None
    total_amount: Decimal | None = None
    status: str | None = None
    metadata: dict | None = None


class InvoiceResponse(BaseModel):
    """Invoice information response."""

    id: UUID
    tenant_id: str
    vendor_id: str
    invoice_number: str
    invoice_date: datetime
    due_date: datetime | None
    currency: str
    line_items: list[InvoiceLineItem]
    subtotal: Decimal
    tax_amount: Decimal
    total_amount: Decimal
    status: str
    metadata: dict | None
    created_at: datetime
    updated_at: datetime


class InvoiceListResponse(BaseModel):
    """Paginated invoice list response."""

    invoices: list[InvoiceResponse]
    total: int
    page: int
    page_size: int