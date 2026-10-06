"""Control-plane dispatcher for webhooks: checkpoint + enqueue (metadata only).

Okta is webhook-only (``POST /api/v1/webhooks/okta`` -> ``sync_okta_license_usage``
worker task); Okta has no pull-sync endpoint. Pull sync exists only for Ramp
(``POST /api/v1/sync/ramp``) and Google Drive (``POST /api/v1/sync/google-drive``,
see ``sync_dispatcher.dispatch_drive_sync``).
"""

import json
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from zellovest_shared.db.models import EntityType, SyncMode
from zellovest_shared.db.repository import acreate_pending_checkpoint
from zellovest_shared.logging_conf import get_logger

logger = get_logger(__name__)


def _enqueue(task_name: str, kwargs: dict) -> str:
    """Lazy-import Celery tasks to avoid control-plane/worker import cycles."""
    from zellovest_workers.tasks.ingestion import (
        handle_ramp_webhook_event,
        sync_okta_license_usage,
        sync_ramp_bills,
        sync_ramp_card_transactions,
    )

    registry = {
        "ramp_webhook": handle_ramp_webhook_event,
        "ramp_card_transactions": sync_ramp_card_transactions,
        "ramp_bills": sync_ramp_bills,
        "okta_license_usage": sync_okta_license_usage,
    }
    async_result = registry[task_name].delay(**kwargs)
    return str(async_result.id)


async def dispatch_ramp_webhook(
    session: AsyncSession,
    *,
    tenant_id: str,
    event_id: str,
    event_type: str,
    object_id: str | None,
) -> tuple[UUID, str, bool]:
    """Write a PENDING event checkpoint and enqueue the Ramp webhook handler."""
    checkpoint, created = await acreate_pending_checkpoint(
        session,
        tenant_id=tenant_id,
        entity=EntityType.EVENTS,
        mode=SyncMode.EVENT_TRIGGERED,
        event_id=event_id,
    )
    if not created:
        logger.info("dispatch_ramp_webhook_deduped", tenant_id=tenant_id, event_id=event_id)
        return checkpoint.sync_id, f"existing:{checkpoint.sync_id}", False

    task_id = _enqueue(
        "ramp_webhook",
        {
            "tenant_id": tenant_id,
            "event_id": event_id,
            "event_type": event_type,
            "object_id": object_id,
            "sync_id": str(checkpoint.sync_id),
        },
    )
    logger.info("dispatch_ramp_webhook_enqueued", tenant_id=tenant_id, event_id=event_id, task_id=task_id)
    return checkpoint.sync_id, task_id, True


async def dispatch_okta_webhook(
    session: AsyncSession,
    *,
    tenant_id: str,
    payload: dict,
) -> tuple[UUID, str, bool]:
    """Write a checkpoint and enqueue Okta webhook handler."""
    event_id = payload.get("uuid", "unknown")
    checkpoint, created = await acreate_pending_checkpoint(
        session,
        tenant_id=tenant_id,
        entity=EntityType.EVENTS,
        mode=SyncMode.EVENT_TRIGGERED,
        event_id=f"okta:{event_id}",
    )
    if not created:
        return checkpoint.sync_id, f"existing:{checkpoint.sync_id}", False

    task_id = _enqueue(
        "okta_license_usage",
        {
            "tenant_id": tenant_id,
            "payload": json.dumps(payload),
            "sync_id": str(checkpoint.sync_id),
        },
    )
    logger.info("dispatch_okta_webhook_enqueued", tenant_id=tenant_id, event_id=event_id, task_id=task_id)
    return checkpoint.sync_id, task_id, True