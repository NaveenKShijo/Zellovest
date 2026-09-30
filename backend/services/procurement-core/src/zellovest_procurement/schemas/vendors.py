"""Vendor schemas."""

from datetime import datetime

from pydantic import BaseModel, Field


class VendorCreate(BaseModel):
    """Request to create a new vendor."""

    tenant_id: str = Field(..., min_length=1, max_length=128)
    name: str = Field(..., min_length=1, max_length=256)
    domain: str | None = Field(default=None, max_length=256)
    category: str | None = Field(default=None, max_length=128)
    metadata: dict | None = None


class VendorUpdate(BaseModel):
    """Request to update vendor information."""

    name: str | None = Field(default=None, min_length=1, max_length=256)
    domain: str | None = Field(default=None, max_length=256)
    category: str | None = Field(default=None, max_length=128)
    metadata: dict | None = None


class VendorResponse(BaseModel):
    """Vendor information response."""

    id: str
    tenant_id: str
    name: str
    domain: str | None
    category: str | None
    metadata: dict | None
    created_at: datetime
    updated_at: datetime


class VendorListResponse(BaseModel):
    """Paginated vendor list response."""

    vendors: list[VendorResponse]
    total: int
    page: int
    page_size: int