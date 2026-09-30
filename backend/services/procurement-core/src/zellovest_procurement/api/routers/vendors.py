"""Vendor management router."""

from datetime import UTC, datetime
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from zellovest_procurement.api.deps import get_db_session
from zellovest_procurement.schemas.vendors import (
    VendorCreate,
    VendorListResponse,
    VendorResponse,
    VendorUpdate,
)
from zellovest_shared.logging_conf import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/vendors", tags=["vendors"])

# TODO: Create proper Vendor model in shared db models (vendors table)


@router.post("", response_model=VendorResponse, status_code=status.HTTP_201_CREATED)
async def create_vendor(
    body: VendorCreate,
    session: AsyncSession = Depends(get_db_session),
) -> VendorResponse:
    """Create a new vendor."""
    # For now, return mock response - actual implementation needs vendor table
    logger.info("vendor_created", tenant_id=body.tenant_id, name=body.name)
    now = datetime.now(UTC)
    return VendorResponse(
        id=str(uuid4()),
        tenant_id=body.tenant_id,
        name=body.name,
        domain=body.domain,
        category=body.category,
        metadata=body.metadata,
        created_at=now,
        updated_at=now,
    )


@router.get("", response_model=VendorListResponse)
async def list_vendors(
    tenant_id: str = Query(..., min_length=1),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    session: AsyncSession = Depends(get_db_session),
) -> VendorListResponse:
    """List vendors for a tenant with pagination."""
    # Mock response for now
    logger.info("vendors_listed", tenant_id=tenant_id)
    return VendorListResponse(
        vendors=[],
        total=0,
        page=page,
        page_size=page_size,
    )


@router.get("/{vendor_id}", response_model=VendorResponse)
async def get_vendor(
    vendor_id: str,
    tenant_id: str = Query(..., min_length=1),
    session: AsyncSession = Depends(get_db_session),
) -> VendorResponse:
    """Get a specific vendor."""
    # Mock response for now
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"Vendor {vendor_id} not found",
    )


@router.patch("/{vendor_id}", response_model=VendorResponse)
async def update_vendor(
    vendor_id: str,
    body: VendorUpdate,
    tenant_id: str = Query(..., min_length=1),
    session: AsyncSession = Depends(get_db_session),
) -> VendorResponse:
    """Update vendor information."""
    logger.info("vendor_updated", vendor_id=vendor_id, tenant_id=tenant_id)
    # Mock response
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"Vendor {vendor_id} not found",
    )


@router.delete("/{vendor_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_vendor(
    vendor_id: str,
    tenant_id: str = Query(..., min_length=1),
    session: AsyncSession = Depends(get_db_session),
) -> None:
    """Delete a vendor."""
    logger.info("vendor_deleted", vendor_id=vendor_id, tenant_id=tenant_id)