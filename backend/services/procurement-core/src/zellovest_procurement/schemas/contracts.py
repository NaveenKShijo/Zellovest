"""Wire schemas for contract history and vendor contract lines."""

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel


class ContractTermResponse(BaseModel):
    """One commercial product line in a contract version."""

    id: UUID
    contract_line_id: UUID
    line_no: int
    product_code: str | None
    description: str | None
    unit_price: Decimal
    currency: str
    uom: str | None
    qty_min: Decimal | None
    qty_max: Decimal | None
    discount_pct: Decimal | None
    tax_rule: str | None
    payment_terms: str | None
    freight_terms: str | None
    effective_from: date
    effective_to: date | None


class ContractVersionResponse(BaseModel):
    """Source document, parent, and terms for one contract version."""

    id: UUID
    version_no: int
    change_type: str
    source_document_id: UUID | None
    source_filename: str | None
    source_upload_id: UUID | None
    parent_version_id: UUID | None
    parent_version_no: int | None
    effective_from: date
    effective_to: date | None
    title: str | None
    contract_start_date: date | None
    contract_end_date: date | None
    renewal_date: date | None
    notice_period_days: int | None
    auto_renew: bool | None
    termination_clause: str | None
    terms: list[ContractTermResponse]


class ContractHistoryResponse(BaseModel):
    """Full source-backed version history for one logical contract."""

    contract_id: UUID
    vendor_id: UUID
    vendor_name: str
    contract_number: str
    title: str | None
    versions: list[ContractVersionResponse]


class VendorContractLineResponse(BaseModel):
    """Latest snapshot line for a vendor's contract table."""

    id: UUID
    contract_id: UUID
    vendor_id: UUID
    contract_number: str
    title: str | None
    product: str
    unit_price: Decimal
    currency: str
    uom: str | None
    qty_min: Decimal | None
    qty_max: Decimal | None
    quantity: Decimal | None
    effective_from: date
    effective_to: date | None
    version: int
    amendment_of_id: UUID | None
    status: str
    payment_terms: str | None
    price_escalation: Decimal | None
    renewal_date: date | None
    auto_renewal: bool | None
    notice_period_days: int | None
    source_document_id: UUID | None
    source_upload_id: UUID | None
    created_at: datetime
    updated_at: datetime
