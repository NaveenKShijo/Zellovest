"""AP Audit & Compliance Reconciliation Schemas."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class APAuditKPIsResponse(BaseModel):
    """Aggregate KPIs for AP Audit & Reconciliation dashboard."""

    total_invoiced_amount: float = Field(..., description="Total billed across all scanned invoices")
    flagged_discrepancy_amount: float = Field(..., description="Total discrepancy amount queued for review")
    total_invoices_count: int = Field(..., description="Total number of invoices evaluated")
    clean_invoices_count: int = Field(..., description="Number of compliant invoices with 0 exceptions")
    exception_invoices_count: int = Field(..., description="Number of invoices flagged with discrepancies")
    unreconciled_invoices_count: int = Field(default=0, description="Number of invoices not yet reconciled against contracts")
    clean_rate_pct: float = Field(..., description="Percentage of compliant invoices among audited")


class LineItemComparisonItem(BaseModel):
    """Line-by-line rate comparison between billed invoice and contracted schedule."""

    id: str
    line_number: int
    product_code: str | None = None
    description: str
    billed_unit_price: float
    contracted_unit_price: float
    billed_quantity: float
    tier_min_quantity: float | None = None
    tier_max_quantity: float | None = None
    variance_amount: float
    extended_variance_amount: float | None = None
    variance_pct: float | None = None
    rule: str
    explanation: str


class ReconciliationExceptionItem(BaseModel):
    """Reconciliation exception record for dashboard presentation."""

    id: UUID
    invoice_id: UUID
    invoice_number: str
    vendor_id: UUID
    vendor_name: str
    invoice_date: str
    due_date: str | None = None
    total_amount: float
    currency: str = "USD"
    discrepancy_amount: float
    primary_rule: str
    rule_label: str
    severity: str
    status: str
    contract_id: UUID
    contract_number: str
    contract_title: str | None = None
    po_number: str | None = None
    detected_at: datetime
    investigation_reason: str
    line_items_comparison: list[LineItemComparisonItem] = Field(default_factory=list)


class ReconciliationExceptionListResponse(BaseModel):
    """Paginated list of reconciliation exceptions."""

    items: list[ReconciliationExceptionItem]
    total: int
    page: int
    page_size: int


class UpdateExceptionStatusRequest(BaseModel):
    """Request payload to transition reconciliation exception status."""

    status: str = Field(..., description="New status: open, acknowledged, resolved, or dismissed")


class ReconcileInvoiceResponse(BaseModel):
    """Response returned upon triggering deterministic reconciliation."""

    tenant_id: str
    invoice_id: str
    status: str
    contract_id: str | None = None
    exception_count: int = 0
    total_discrepancy_amount: float = 0.0
