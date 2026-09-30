"""Manual/scheduled sync trigger router."""

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from zellovest_ingestion.api.deps import get_db_session
from zellovest_ingestion.schemas.sync import SyncRequest, SyncResponse
from zellovest_ingestion.services.sync_dispatcher import dispatch_sync_task
from zellovest_shared.logging_conf import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/sync", tags=["sync"])


@router.post("/ramp", response_model=SyncResponse, status_code=status.HTTP_202_ACCEPTED)
async def trigger_ramp_sync(
    body: SyncRequest,
    session: AsyncSession = Depends(get_db_session),
) -> SyncResponse:
    """Enqueue a Ramp polling task (card_transactions, bills)."""
    sync_id, task_id, created = await dispatch_sync_task(
        session,
        tenant_id=body.tenant_id,
        source="ramp",
        entity=body.entity,
        cursor=body.cursor,
        date_from=body.date_from,
        date_to=body.date_to,
    )
    await session.commit()
    logger.info("ramp_sync_triggered", tenant_id=body.tenant_id, entity=body.entity, created=created)
    return SyncResponse(sync_id=sync_id, task_id=task_id, status="PENDING", deduped=not created)


@router.post("/okta", response_model=SyncResponse, status_code=status.HTTP_202_ACCEPTED)
async def trigger_okta_sync(
    body: SyncRequest,
    session: AsyncSession = Depends(get_db_session),
) -> SyncResponse:
    """Enqueue an Okta sync task (license usage)."""
    sync_id, task_id, created = await dispatch_sync_task(
        session,
        tenant_id=body.tenant_id,
        source="okta",
        entity=body.entity or "license_usage",
        cursor=body.cursor,
        date_from=body.date_from,
        date_to=body.date_to,
    )
    await session.commit()
    logger.info("okta_sync_triggered", tenant_id=body.tenant_id, entity=body.entity, created=created)
    return SyncResponse(sync_id=sync_id, task_id=task_id, status="PENDING", deduped=not created)