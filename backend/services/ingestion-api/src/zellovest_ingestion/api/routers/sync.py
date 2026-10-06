"""Manual/scheduled pull-sync router (Ramp + Google Drive; Okta is webhook-only).

Sync matrix:
- Ramp: ``POST /api/v1/sync/ramp`` (pull ``card_transactions`` / ``bills``).
- Google Drive: ``POST /api/v1/sync/google-drive`` (pull via ``changes.list``
  from the checkpoint cursor; worker fans files out to ``document_tasks``).
- Okta: webhook-only (``POST /api/v1/webhooks/okta``); no pull-sync endpoint.
"""

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from zellovest_ingestion.api.deps import get_db_session
from zellovest_ingestion.schemas.sync import DriveSyncRequest, SyncRequest, SyncResponse
from zellovest_ingestion.services.sync_dispatcher import dispatch_drive_sync, dispatch_sync_task
from zellovest_shared.logging_conf import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/sync", tags=["sync"])


@router.post("/ramp", response_model=SyncResponse, status_code=status.HTTP_202_ACCEPTED)
async def trigger_ramp_sync(
    body: SyncRequest,
    session: AsyncSession = Depends(get_db_session),
) -> SyncResponse:
    """Enqueue a Ramp pull-sync task (``card_transactions``, ``bills``)."""
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
    return SyncResponse(sync_id=str(sync_id), task_id=task_id, status="PENDING", deduped=not created)


@router.post("/google-drive", response_model=SyncResponse, status_code=status.HTTP_202_ACCEPTED)
async def trigger_drive_sync(
    body: DriveSyncRequest,
    session: AsyncSession = Depends(get_db_session),
) -> SyncResponse:
    """Enqueue a Google Drive pull-sync task (``changes.list`` from cursor)."""
    sync_id, task_id, created = await dispatch_drive_sync(
        session,
        tenant_id=body.tenant_id,
        cursor=body.cursor,
        full_sync=body.full_sync,
        page_size=body.page_size,
    )
    await session.commit()
    logger.info(
        "drive_sync_triggered",
        tenant_id=body.tenant_id,
        full_sync=body.full_sync,
        created=created,
    )
    return SyncResponse(sync_id=str(sync_id), task_id=task_id, status="PENDING", deduped=not created)
