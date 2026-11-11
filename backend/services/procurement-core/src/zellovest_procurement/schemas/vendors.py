"""Vendor schemas for Procurement Core Service."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class PrimaryContact(BaseModel):
    """Primary contact details for a vendor."""

    name: str | None = None
    email: str | None = None
    phone: str | None = None


class VendorCreate(BaseModel):
    """Request to create a new vendor."""

    tenant_id: str | None = None
    name: str | None = None
    canonicalName: str | None = None
    domain: str | None = Field(default=None, max_length=256)
    category: str | None = Field(default=None, max_length=128)
    categories: list[str] | None = None
    payment_terms: str | None = None
    paymentTerms: str | None = None
    customPaymentTerms: str | None = None
    status: str | None = "compliant"
    primaryContact: PrimaryContact | None = None
    metadata: dict[str, Any] | None = None


class VendorUpdate(BaseModel):
    """Request to update vendor information."""

    name: str | None = Field(default=None, min_length=1, max_length=256)
    canonicalName: str | None = None
    domain: str | None = Field(default=None, max_length=256)
    category: str | None = Field(default=None, max_length=128)
    categories: list[str] | None = None
    payment_terms: str | None = None
    paymentTerms: str | None = None
    customPaymentTerms: str | None = None
    status: str | None = None
    primaryContact: PrimaryContact | None = None
    metadata: dict[str, Any] | None = None


class VendorResponse(BaseModel):
    """Vendor information response with spend metrics and counts."""

    id: str
    tenant_id: str | None = None
    name: str
    canonicalName: str
    domain: str | None = None
    primaryContact: PrimaryContact | None = None
    paymentTerms: str = "net_30"
    customPaymentTerms: str | None = None
    categories: list[str] = Field(default_factory=list)
    category: str | None = None
    annualSpend: float = 0.0
    currency: str = "USD"
    status: str = "compliant"
    contractCount: int = 0
    invoiceCount: int = 0
    transactionCount: int = 0
    metadata: dict[str, Any] | None = None
    createdAt: str
    updatedAt: str
    created_at: datetime | None = None
    updated_at: datetime | None = None

    model_config = ConfigDict(populate_by_name=True)


class VendorListResponse(BaseModel):
    """Paginated vendor list response."""

    vendors: list[VendorResponse]
    total: int
    page: int
    pageSize: int = Field(default=10, serialization_alias="pageSize")
    page_size: int = Field(default=10, serialization_alias="page_size")
    totalPages: int = Field(default=1, serialization_alias="totalPages")

    model_config = ConfigDict(populate_by_name=True)
