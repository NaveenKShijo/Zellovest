"""Ingestion data-plane tasks: Ramp polling + webhook handlers, Okta sync.

Task signatures carry metadata IDs only (``tenant_id``, ``cursor``,
``event_id``, ``sync_id``). Workers fetch bytes from source APIs directly and
stream gzipped JSONL into the partitioned S3 bronze lake. Raw payloads
never touch Redis.
"""

import uuid
from typing import Any

import httpx
from celery import Task
from sqlalchemy import select

from zellovest_shared.config import get_settings
from zellovest_shared.db.models import EntityType, IngestionSyncCheckpoint, SyncStatus, TenantIntegration
from zellovest_shared.db.repository import mark_checkpoint
from zellovest_shared.db.session import get_session_factory
from zellovest_shared.logging_conf import get_logger
from zellovest_shared.security.crypto import decrypt_token
from zellovest_shared.workers.ramp_client import RampClient, RateLimitError, TransientRampError
from zellovest_shared.workers.s3_writer import ENTITY_FOLDERS, write_records_gz
from zellovest_workers.celery_app import QUEUE_INGESTION, celery_app

logger = get_logger(__name__)

_RETRY_KWARGS: dict[str, Any] = {
    "autoretry_for": (
        TransientRampError,
        RateLimitError,
        httpx.TimeoutException,
        httpx.ConnectError,
    ),
    "max_retries": 5,
    "retry_backoff": True,
    "retry_backoff_max": 600,
    "retry_jitter": True,
}


def _settings() -> Any:
    """Return settings, tolerating missing env in unit-test contexts."""
    try:
        return get_settings()
    except Exception:  # pragma: no cover - tests inject fakes
        return None


def _load_access_token(session: Any, tenant_id: str, key_b64: str) -> str:
    """Load and decrypt the tenant's access token (in-memory only)."""
    row = session.execute(
        select(TenantIntegration).where(TenantIntegration.tenant_id == tenant_id)
    ).scalar_one_or_none()
    if row is None:
        raise ValueError(f"no integration for tenant {tenant_id}")
    return decrypt_token(row.encrypted_access_token, row.encryption_nonce, key_b64)


def _get_checkpoint(session: Any, sync_id: str) -> IngestionSyncCheckpoint | None:
    """Fetch the checkpoint ticket for this task, if it still exists."""
    try:
        wanted = uuid.UUID(sync_id)
    except ValueError:
        return None
    return session.execute(
        select(IngestionSyncCheckpoint).where(IngestionSyncCheckpoint.sync_id == wanted)
    ).scalar_one_or_none()


def _poll_entity(
    self: Task,
    *,
    tenant_id: str,
    entity: str,
    cursor: str | None,
    sync_id: str | None,
) -> dict[str, Any]:
    """Shared keyset-polling engine: paginate Ramp -> gzip batches -> S3."""
    settings = _settings()
    factory = get_session_factory()
    session = factory()
    try:
        checkpoint = _get_checkpoint(session, sync_id or "") if sync_id else None
        if checkpoint is not None:
            mark_checkpoint(session, checkpoint, status=SyncStatus.RUNNING)
            session.commit()

        access_token = _load_access_token(
            session, tenant_id, settings.credentials_encryption_key if settings else ""
        )
        client = RampClient(
            settings.ramp_api_base_url if settings else "https://api.ramp.com", access_token
        )
        batch_size = settings.poll_batch_size if settings else 100

        next_cursor = cursor
        pages = 0
        total_records = 0
        keys: list[str] = []
        while True:
            try:
                records, next_cursor = client.fetch_page(
                    entity, cursor=next_cursor, page_size=batch_size
                )
            except RateLimitError as exc:
                logger.warning("poll_rate_limited", tenant_id=tenant_id, entity=entity)
                raise self.retry(exc=exc, countdown=exc.retry_after_seconds)
            if not records:
                break
            key = write_records_gz(
                records,
                bucket=settings.s3_raw_bucket if settings else "tenant-bucket",
                entity_folder=ENTITY_FOLDERS.get(entity, entity),
                sync_id=sync_id or "no-sync",
                suffix=f"cursor-{next_cursor or 'final'}",
                endpoint_url=settings.s3_endpoint_url if settings else None,
                region=settings.aws_region if settings else "us-east-1",
            )
            keys.append(key)
            total_records += len(records)
            pages += 1
            if checkpoint is not None:
                mark_checkpoint(
                    session, checkpoint, status=SyncStatus.RUNNING, cursor_token=next_cursor
                )
                session.commit()
            if not next_cursor:
                break

        if checkpoint is not None:
            mark_checkpoint(
                session, checkpoint, status=SyncStatus.SUCCESS, cursor_token=next_cursor
            )
            session.commit()
        logger.info(
            "poll_complete", tenant_id=tenant_id, entity=entity, pages=pages, records=total_records
        )
        return {"sync_id": sync_id, "pages": pages, "records": total_records, "keys": keys}
    except (TransientRampError, RateLimitError, httpx.TimeoutException, httpx.ConnectError):
        raise
    except Exception as exc:
        if checkpoint is not None:
            try:
                mark_checkpoint(
                    session,
                    checkpoint,
                    status=SyncStatus.FAILED,
                    error_log=f"{type(exc).__name__}: {exc}",
                )
                session.commit()
            except Exception:
                session.rollback()
        logger.error(
            "poll_failed", tenant_id=tenant_id, entity=entity, error_class=type(exc).__name__
        )
        raise
    finally:
        session.close()


@celery_app.task(
    name="zellovest.workers.tasks.ingestion.sync_ramp_card_transactions",
    bind=True,
    queue=QUEUE_INGESTION,
    **_RETRY_KWARGS,
)
def sync_ramp_card_transactions(
    self: Task, tenant_id: str, cursor: str | None = None, sync_id: str | None = None
) -> dict[str, Any]:
    """Poll Ramp card transactions (backfill/incremental/scheduled)."""
    return _poll_entity(
        self,
        tenant_id=tenant_id,
        entity=EntityType.CARD_TRANSACTIONS.value,
        cursor=cursor,
        sync_id=sync_id,
    )


@celery_app.task(
    name="zellovest.workers.tasks.ingestion.sync_ramp_bills",
    bind=True,
    queue=QUEUE_INGESTION,
    **_RETRY_KWARGS,
)
def sync_ramp_bills(
    self: Task, tenant_id: str, cursor: str | None = None, sync_id: str | None = None
) -> dict[str, Any]:
    """Poll Ramp bills (backfill/incremental/scheduled)."""
    return _poll_entity(
        self, tenant_id=tenant_id, entity=EntityType.BILLS.value, cursor=cursor, sync_id=sync_id
    )


@celery_app.task(
    name="zellovest.workers.tasks.ingestion.handle_ramp_webhook_event",
    bind=True,
    queue=QUEUE_INGESTION,
    **_RETRY_KWARGS,
)
def handle_ramp_webhook_event(
    self: Task,
    tenant_id: str,
    event_id: str,
    event_type: str = "unknown",
    object_id: str | None = None,
    sync_id: str | None = None,
) -> dict[str, Any]:
    """Handle one Ramp pushed event: validate -> fetch -> gzip -> S3."""
    del self  # bound task unused beyond retry config
    settings = _settings()
    factory = get_session_factory()
    session = factory()
    try:
        checkpoint = _get_checkpoint(session, sync_id or "") if sync_id else None
        if checkpoint is not None:
            mark_checkpoint(session, checkpoint, status=SyncStatus.RUNNING)
            session.commit()

        if not event_id or not tenant_id:
            raise ValueError("webhook task missing tenant_id/event_id")

        access_token = _load_access_token(
            session, tenant_id, settings.credentials_encryption_key if settings else ""
        )
        client = RampClient(
            settings.ramp_api_base_url if settings else "https://api.ramp.com", access_token
        )

        if object_id:
            record = client.fetch_object("events", object_id)
            record.setdefault("event_id", event_id)
            record.setdefault("event_type", event_type)
            records = [record]
        else:
            records = [{"event_id": event_id, "event_type": event_type, "object_id": object_id}]

        key = write_records_gz(
            records,
            bucket=settings.s3_raw_bucket if settings else "tenant-bucket",
            entity_folder=ENTITY_FOLDERS["events"],
            sync_id=sync_id or "no-sync",
            suffix=f"event-{event_id}",
            endpoint_url=settings.s3_endpoint_url if settings else None,
            region=settings.aws_region if settings else "us-east-1",
        )
        if checkpoint is not None:
            mark_checkpoint(session, checkpoint, status=SyncStatus.SUCCESS)
            session.commit()
        logger.info("webhook_handled", tenant_id=tenant_id, event_id=event_id)
        return {"sync_id": sync_id, "event_id": event_id, "key": key}
    except (TransientRampError, RateLimitError, httpx.TimeoutException, httpx.ConnectError):
        raise
    except Exception as exc:
        if checkpoint is not None:
            try:
                mark_checkpoint(
                    session,
                    checkpoint,
                    status=SyncStatus.FAILED,
                    error_log=f"{type(exc).__name__}: {exc}",
                )
                session.commit()
            except Exception:
                session.rollback()
        logger.error(
            "webhook_failed", tenant_id=tenant_id, event_id=event_id, error_class=type(exc).__name__
        )
        raise
    finally:
        session.close()


@celery_app.task(
    name="zellovest.workers.tasks.ingestion.sync_okta_license_usage",
    bind=True,
    queue=QUEUE_INGESTION,
    **_RETRY_KWARGS,
)
def sync_okta_license_usage(
    self: Task,
    tenant_id: str,
    cursor: str | None = None,
    sync_id: str | None = None,
    payload: str | None = None,
) -> dict[str, Any]:
    """Sync Okta app assignments / user activity into the bronze lake.

    Supports both scheduled polling (cursor) and webhook-triggered single
    payloads. Writes normalized usage snapshots to S3 for the Zombie License
    engine to consume deterministically.
    """
    del self
    settings = _settings()
    records: list[dict[str, Any]] = []
    if payload:
        import json

        try:
            records = [json.loads(payload)] if isinstance(payload, str) else [payload]
        except Exception:
            records = [{"raw": payload}]
    else:
        # TODO: implement Okta System Log / Apps API pagination with cursor.
        logger.info("okta_sync_stub", tenant_id=tenant_id, cursor=cursor)
        return {"sync_id": sync_id, "records": 0, "keys": [], "note": "okta pagination TODO"}

    key = write_records_gz(
        records,
        bucket=settings.s3_raw_bucket if settings else "tenant-bucket",
        entity_folder="events",
        sync_id=sync_id or "no-sync",
        suffix="okta-usage",
        endpoint_url=settings.s3_endpoint_url if settings else None,
        region=settings.aws_region if settings else "us-east-1",
    )
    logger.info("okta_sync_complete", tenant_id=tenant_id, records=len(records))
    return {"sync_id": sync_id, "records": len(records), "keys": [key] if key else []}
