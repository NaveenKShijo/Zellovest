"""Tenant management router."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from zellovest_procurement.api.deps import get_db_session
from zellovest_procurement.schemas.tenants import TenantCreate, TenantResponse, TenantUpdate
from zellovest_shared.db.models import TenantIntegration
from zellovest_shared.logging_conf import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/tenants", tags=["tenants"])


@router.post("", response_model=TenantResponse, status_code=status.HTTP_201_CREATED)
async def create_tenant(
    body: TenantCreate,
    session: AsyncSession = Depends(get_db_session),
) -> TenantResponse:
    """Register a new tenant in the deployment."""
    # Check if tenant already has integration
    existing = await session.execute(
        select(TenantIntegration).where(TenantIntegration.tenant_id == body.tenant_id)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Tenant {body.tenant_id} already exists",
        )

    # For now, just return success - actual integration is via OAuth
    logger.info("tenant_registered", tenant_id=body.tenant_id)
    return TenantResponse(
        tenant_id=body.tenant_id,
        name=body.name,
        status="registered",
    )


@router.get("/{tenant_id}", response_model=TenantResponse)
async def get_tenant(
    tenant_id: str,
    session: AsyncSession = Depends(get_db_session),
) -> TenantResponse:
    """Get tenant information."""
    integration = await session.execute(
        select(TenantIntegration).where(TenantIntegration.tenant_id == tenant_id)
    )
    row = integration.scalar_one_or_none()
    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tenant {tenant_id} not found",
        )

    return TenantResponse(
        tenant_id=row.tenant_id,
        name=tenant_id,  # Could store name separately
        status=row.connection_status.value.lower(),
    )


@router.patch("/{tenant_id}", response_model=TenantResponse)
async def update_tenant(
    tenant_id: str,
    body: TenantUpdate,
    session: AsyncSession = Depends(get_db_session),
) -> TenantResponse:
    """Update tenant metadata."""
    integration = await session.execute(
        select(TenantIntegration).where(TenantIntegration.tenant_id == tenant_id)
    )
    row = integration.scalar_one_or_none()
    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tenant {tenant_id} not found",
        )

    # Update metadata (connection_status etc. handled by OAuth)
    logger.info("tenant_updated", tenant_id=tenant_id)
    return TenantResponse(
        tenant_id=row.tenant_id,
        name=tenant_id,
        status=row.connection_status.value.lower(),
    )


@router.delete("/{tenant_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_tenant(
    tenant_id: str,
    session: AsyncSession = Depends(get_db_session),
) -> None:
    """Delete a tenant and all associated data."""
    integration = await session.execute(
        select(TenantIntegration).where(TenantIntegration.tenant_id == tenant_id)
    )
    row = integration.scalar_one_or_none()
    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tenant {tenant_id} not found",
        )

    await session.delete(row)
    await session.commit()
    logger.info("tenant_deleted", tenant_id=tenant_id)