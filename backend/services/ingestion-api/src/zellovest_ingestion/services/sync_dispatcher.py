"""Sync task dispatcher for manual/scheduled syncs."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from zellovest_shared.db.models import EntityType, SyncMode
from zellovest_shared.db.repository import acreate_pending_checkpoint
from zellovest_shared.logging_conf import get_logger

logger = get_logger(__name__)


def _enqueue(source: str, entity: str, kwargs: dict) -> str:
    """Lazy-import Celery tasks."""
    if source == "ramp":
        from zellovest_workers.tasks.ingestion import (
            sync_ramp_bills,
            sync_ramp_card_transactions,
        )
        registry = {
            "card_transactions": sync_ramp_card_transactions,
            "bills": sync_ramp_bills,
        }
    elif source == "okta":
        from zellovest_workers.tasks.ingestion import sync_okta_license_usage
        registry = {
            "license_usage": sync_okta_license_usage,
        }
    else:
        raise ValueError(f"Unknown source: {source}")

    async_result = registry[entity].delay(**kwargs)
    return str(async_result.id)


async def dispatch_sync_task(
    session: AsyncSession,
    *,
    tenant_id: str,
    source: str,
    entity: str,
    cursor: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> tuple[UUID, str, bool]:
    """Write a PENDING checkpoint and enqueue a sync task."""
    # Map entity string to EntityType enum
    entity_map = {
        "card_transactions": EntityType.CARD_TRANSACTIONS,
        "bills": EntityType.BILLS,
        "license_usage": EntityType.EVENTS,  # reuse for now
        "invoices": EntityType.INVOICES,
        "contracts": EntityType.CONTRACTS,
    }
    entity_type = entity_map.get(entity)
    if not entity_type:
        raise ValueError(f"Unknown entity: {entity}")

    mode = SyncMode.BACKFILL if (date_from or date_to) else SyncMode.INCREMENTAL

    checkpoint, created = await acreate_pending_checkpoint(
        session,
        tenant_id=tenant_id,
        entity=entity_type,
        mode=mode,
        cursor_token=cursor,
        date_from=date_from,
        date_to=date_to,
    )
    if not created:
        logger.info("dispatch_sync_deduped", tenant_id=tenant_id, sync_id=str(checkpoint.sync_id))
        return checkpoint.sync_id, f"existing:{checkpoint.sync_id}", False

    task_id = _enqueue(source, entity, {
        "tenant_id": tenant_id,
        "cursor": cursor,
        "sync_id": str(checkpoint.sync_id),
    })
    logger.info("dispatch_sync_enqueued", tenant_id=tenant_id, sync_id=str(checkpoint.sync_id), task_id=task_id)
    return checkpoint.sync_id, task_id, True