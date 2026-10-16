"""Manual/scheduled pull-sync router (Ramp + Google Drive + Okta batch).

Sync matrix:
- Ramp: ``POST /api/v1/sync/ramp`` (pull ``card_transactions`` / ``bills``).
- Google Drive: ``POST /api/v1/sync/google-drive`` (pull via ``changes.list``
  from the checkpoint cursor; worker fans files out to ``document_tasks``).
- Okta: ``POST /api/v1/sync/okta`` (batch pull ``users`` / ``apps`` / ``logs``;
  backfill + reconciliation path alongside the ``/webhooks/okta`` real-time path).
"""

import inspect

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from zellovest_ingestion.api.deps import get_db_session
from zellovest_ingestion.schemas.sync import DriveSyncRequest, OktaSyncRequest, SyncRequest, SyncResponse
from zellovest_ingestion.services.sync_dispatcher import (
    dispatch_drive_sync,
    dispatch_okta_sync,
    dispatch_sync_task,
)
from zellovest_shared.db.models import TenantIntegration, effective_connection_status
from zellovest_shared.logging_conf import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/sync", tags=["sync"])


async def _require_usable_integration(
    session: AsyncSession, *, tenant_id: str, provider: str
) -> None:
    """Reject a sync with 409 when the OAuth connection needs a reconnect.

    Lets "Sync Now" fail fast with an actionable message instead of
    queueing a job that silently fails in the worker.

    Args:
        session: Async DB session.
        tenant_id: Tenant requesting the sync.
        provider: Provider key (``ramp`` / ``okta``).

    Raises:
        HTTPException: 409 when the stored connection is EXPIRED/REVOKED
            or its access token has passed ``token_expires_at``.
    """
    try:
        result = await session.execute(
            select(TenantIntegration).where(
                TenantIntegration.tenant_id == tenant_id,
                TenantIntegration.provider == provider,
            )
        )
        scalar = result.scalar_one_or_none()
        if inspect.isawaitable(scalar):
            scalar = await scalar
    except Exception:
        # Best-effort gate only: a lookup failure must not block the sync —
        # the worker surfaces auth errors and marks the row itself.
        logger.warning(
            "sync_reconnect_check_skipped",
            tenant_id=tenant_id,
            provider=provider,
        )
        return
    if not isinstance(scalar, TenantIntegration):
        # No row (or a non-DB test double): nothing to gate on.
        return
    row = scalar
    # SSWS Okta rows (static API token, no offline_access scope) never
    # expire — only gate OAuth Bearer rows.
    if provider == "okta" and "offline_access" not in (row.scopes or []):
        return
    effective = effective_connection_status(row.connection_status, row.token_expires_at)
    if effective.value in ("EXPIRED", "REVOKED"):
        logger.warning(
            "sync_rejected_needs_reconnect",
            tenant_id=tenant_id,
            provider=provider,
            status=effective.value,
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"{provider} access token {effective.value.lower()} — "
                "reconnect the integration in /integrations, then retry the sync"
            ),
        )


@router.post("/ramp", response_model=SyncResponse, status_code=status.HTTP_202_ACCEPTED)
async def trigger_ramp_sync(
    body: SyncRequest,
    session: AsyncSession = Depends(get_db_session),
) -> SyncResponse:
    """Enqueue a Ramp pull-sync task (``card_transactions``, ``bills``)."""
    await _require_usable_integration(session, tenant_id=body.tenant_id, provider="ramp")
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
    logger.info("ramp_sync_triggered", tenant_id=body.tenant_id,
        entity=body.entity, created=created)
    return SyncResponse(sync_id=str(sync_id), task_id=task_id,
        status="PENDING", deduped=not created)


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


@router.post("/okta", response_model=SyncResponse, status_code=status.HTTP_202_ACCEPTED)
async def trigger_okta_sync(
    body: OktaSyncRequest,
    session: AsyncSession = Depends(get_db_session),
) -> SyncResponse:
    """Enqueue an Okta batch pull (``users`` / ``apps`` / ``logs``).

    Real-time events keep arriving via ``POST /webhooks/okta``; use this
    endpoint for initial backfill, scheduled reconciliation, or recovery
    after an outage. Requires ``OKTA_DOMAIN`` plus an SSWS token
    (per-tenant ``okta`` integration row or ``OKTA_API_TOKEN`` fallback)
    with ``okta.users.read``, ``okta.apps.read``, ``okta.logs.read``.
    """
    await _require_usable_integration(session, tenant_id=body.tenant_id, provider="okta")
    sync_id, task_id, created = await dispatch_okta_sync(
        session,
        tenant_id=body.tenant_id,
        entities=list(body.entities),
        cursor=body.cursor,
        since=body.since,
        until=body.until,
        page_size=body.page_size,
    )
    await session.commit()
    logger.info(
        "okta_sync_triggered",
        tenant_id=body.tenant_id,
        entities=body.entities,
        created=created,
    )
    return SyncResponse(sync_id=str(sync_id), task_id=task_id, status="PENDING", deduped=not created)
