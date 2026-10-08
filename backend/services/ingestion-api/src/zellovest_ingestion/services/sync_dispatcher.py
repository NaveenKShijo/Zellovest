"""Pull-sync task dispatcher (Ramp + Google Drive + Okta batch).

- Ramp pull sync (``POST /api/v1/sync/ramp``): PENDING checkpoint + enqueue a
  Celery polling task (``dispatch_sync_task``).
- Drive pull sync (``POST /api/v1/sync/google-drive``): PENDING checkpoint on
  the ``documents`` entity (cursor = ``changes.list`` pageToken) + enqueue the
  ``sync_drive_changes`` worker task (``dispatch_drive_sync``). The worker
  data plane pages ``changes.list`` from the cursor (or a fresh
  ``startPageToken`` on full sync) and fans files out to ``document_tasks``.
- Okta batch pull (``POST /api/v1/sync/okta``): PENDING checkpoint on the
  ``events`` entity (cursor = System Log ``after`` cursor) + enqueue the
  ``sync_okta_batch`` worker task (``dispatch_okta_sync``). Webhook delivery
  (``POST /api/v1/webhooks/okta``, see ``dispatcher``) stays the real-time
  path; batch pull is the backfill/reconciliation path.
"""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from zellovest_shared.db.models import EntityType, SyncMode
from zellovest_shared.db.repository import acreate_pending_checkpoint
from zellovest_shared.logging_conf import get_logger

logger = get_logger(__name__)

_RAMP_ENTITIES = frozenset({"card_transactions", "bills"})

DRIVE_SYNC_TASK_NAME = "zellovest.workers.tasks.ingestion.sync_drive_changes"

OKTA_SYNC_TASK_NAME = "zellovest.workers.tasks.ingestion.sync_okta_batch"

_OKTA_ENTITIES = frozenset({"users", "apps", "logs"})


def _enqueue(source: str, entity: str, kwargs: dict) -> str:
    """Lazy-import Celery tasks.

    Args:
        source: Only ``"ramp"`` is supported for pull sync.
        entity: One of ``card_transactions`` / ``bills``.

    Raises:
        ValueError: For any non-Ramp source/entity (Okta has no pull sync).
    """
    if source != "ramp":
        raise ValueError(f"Pull sync not supported for source: {source} (ramp only)")
    if entity not in _RAMP_ENTITIES:
        raise ValueError(f"Unknown Ramp entity: {entity}")
    from zellovest_workers.tasks.ingestion import (
        sync_ramp_bills,
        sync_ramp_card_transactions,
    )

    registry = {
        "card_transactions": sync_ramp_card_transactions,
        "bills": sync_ramp_bills,
    }

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
    """Write a PENDING checkpoint and enqueue a Ramp pull-sync task.

    Raises:
        ValueError: If ``source`` is not ``"ramp"`` or ``entity`` is not a
            Ramp entity. Okta pull sync was removed; use the Okta webhook.
    """
    if source != "ramp":
        raise ValueError(f"Pull sync not supported for source: {source} (ramp only)")
    # Map entity string to EntityType enum (Ramp entities only).
    entity_map = {
        "card_transactions": EntityType.CARD_TRANSACTIONS,
        "bills": EntityType.BILLS,
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


def _enqueue_drive(kwargs: dict) -> str:
    """Enqueue the Drive ``changes.list`` poll task by name.

    Sent by task name (not a direct import) so the API control plane does not
    hard-depend on the worker implementation: the ``sync_drive_changes`` task
    (queue ``ingestion_tasks`` via the ``ingestion.*`` route wildcard) pages
    Drive from the checkpoint cursor and fans files out to ``document_tasks``.
    """
    from zellovest_workers.celery_app import celery_app

    async_result = celery_app.send_task(DRIVE_SYNC_TASK_NAME, kwargs=kwargs)
    return str(async_result.id)


async def dispatch_drive_sync(
    session: AsyncSession,
    *,
    tenant_id: str,
    cursor: str | None = None,
    full_sync: bool = False,
    page_size: int = 100,
) -> tuple[UUID, str, bool]:
    """Write a PENDING checkpoint and enqueue a Drive pull-sync task.

    Cursor resolution: explicit ``cursor`` wins; otherwise the latest SUCCESS
    cursor for the ``documents`` entity resumes the stream (``full_sync``
    skips the stored cursor so the worker re-seeds ``startPageToken``).

    Args:
        session: Async DB session.
        tenant_id: Tenant to sync.
        cursor: ``changes.list`` pageToken override (optional).
        full_sync: Ignore the stored cursor and re-seed.
        page_size: Items per ``changes.list`` page (1-1000).

    Returns:
        Tuple of (sync_id, task_id, created); ``created=False`` means the
        request deduped onto an already-open checkpoint.
    """
    from zellovest_shared.db.repository import aget_latest_success_cursor

    effective_cursor = cursor
    if effective_cursor is None and not full_sync:
        effective_cursor = await aget_latest_success_cursor(
            session, tenant_id=tenant_id, entity=EntityType.DOCUMENTS
        )

    mode = SyncMode.BACKFILL if (full_sync or cursor) else SyncMode.INCREMENTAL

    checkpoint, created = await acreate_pending_checkpoint(
        session,
        tenant_id=tenant_id,
        entity=EntityType.DOCUMENTS,
        mode=mode,
        cursor_token=effective_cursor,
    )
    if not created:
        logger.info(
            "dispatch_drive_sync_deduped",
            tenant_id=tenant_id,
            sync_id=str(checkpoint.sync_id),
        )
        return checkpoint.sync_id, f"existing:{checkpoint.sync_id}", False

    task_id = _enqueue_drive({
        "tenant_id": tenant_id,
        "cursor": effective_cursor,
        "sync_id": str(checkpoint.sync_id),
        "page_size": min(max(page_size, 1), 1000),
    })
    logger.info(
        "dispatch_drive_sync_enqueued",
        tenant_id=tenant_id,
        sync_id=str(checkpoint.sync_id),
        task_id=task_id,
    )
    return checkpoint.sync_id, task_id, True


def _enqueue_okta(kwargs: dict) -> str:
    """Enqueue the Okta batch-pull task by name (no hard worker import)."""
    from zellovest_workers.celery_app import celery_app

    async_result = celery_app.send_task(OKTA_SYNC_TASK_NAME, kwargs=kwargs)
    return str(async_result.id)


async def dispatch_okta_sync(
    session: AsyncSession,
    *,
    tenant_id: str,
    entities: list[str] | None = None,
    cursor: str | None = None,
    since: str | None = None,
    until: str | None = None,
    page_size: int = 200,
) -> tuple[UUID, str, bool]:
    """Write a PENDING checkpoint and enqueue an Okta batch-pull task.

    Checkpoints reuse the ``events`` entity (no schema migration); the cursor
    is the System Log ``after`` cursor. Explicit ``cursor`` wins, otherwise
    the latest SUCCESS cursor resumes the stream.

    Raises:
        ValueError: On unknown entity names.
    """
    from zellovest_shared.db.repository import aget_latest_success_cursor

    wanted = entities or ["users", "apps", "logs"]
    unknown = [e for e in wanted if e not in _OKTA_ENTITIES]
    if unknown:
        raise ValueError(f"Unknown Okta entities: {unknown}")

    effective_cursor = cursor
    if effective_cursor is None:
        effective_cursor = await aget_latest_success_cursor(
            session, tenant_id=tenant_id, entity=EntityType.EVENTS
        )

    mode = SyncMode.BACKFILL if (since or until or cursor) else SyncMode.INCREMENTAL

    checkpoint, created = await acreate_pending_checkpoint(
        session,
        tenant_id=tenant_id,
        entity=EntityType.EVENTS,
        mode=mode,
        cursor_token=effective_cursor,
        date_from=since,
        date_to=until,
    )
    if not created:
        logger.info(
            "dispatch_okta_sync_deduped",
            tenant_id=tenant_id,
            sync_id=str(checkpoint.sync_id),
        )
        return checkpoint.sync_id, f"existing:{checkpoint.sync_id}", False

    task_id = _enqueue_okta({
        "tenant_id": tenant_id,
        "entities": wanted,
        "cursor": effective_cursor,
        "since": since,
        "until": until,
        "page_size": min(max(page_size, 1), 200),
        "sync_id": str(checkpoint.sync_id),
    })
    logger.info(
        "dispatch_okta_sync_enqueued",
        tenant_id=tenant_id,
        sync_id=str(checkpoint.sync_id),
        task_id=task_id,
    )
    return checkpoint.sync_id, task_id, True
