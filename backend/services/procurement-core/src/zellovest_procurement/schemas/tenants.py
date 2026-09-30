"""Tenant schemas."""

from pydantic import BaseModel, Field


class TenantCreate(BaseModel):
    """Request to register a new tenant."""

    tenant_id: str = Field(..., min_length=1, max_length=128)
    name: str = Field(..., min_length=1, max_length=256)


class TenantUpdate(BaseModel):
    """Request to update tenant metadata."""

    name: str | None = Field(default=None, min_length=1, max_length=256)


class TenantResponse(BaseModel):
    """Tenant information response."""

    tenant_id: str
    name: str
    status: str