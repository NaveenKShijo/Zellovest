"""Idempotent repository helpers for integrations and checkpoints.

All writers are safe under duplicate webhook/manual-sync delivery:
- ``upsert_integration`` keyed on ``tenant_id`` (single-tenant: one row).
- ``create_pending_checkpoint`` returns the existing open checkpoint when a
  duplicate arrives instead of creating a race (checked via ``event_id``
  for webhooks, via open PENDING/RUNNING row for manual syncs).
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from zellovest_shared.db.models import (
    ConnectionStatus,
    EntityType,
    IngestionSyncCheckpoint,
    SyncMode,
    SyncStatus,
    TenantIntegration,
)
from zellovest_shared.logging_conf import get_logger

logger = get_logger(__name__)


def upsert_integration_sync(
    session: Session,
    *,
    tenant_id: str,
    encrypted_access_token: bytes,
    encrypted_refresh_token: bytes,
    encryption_nonce: bytes,
    token_expires_at: datetime | None,
    scopes: list[str] | None = None,
) -> TenantIntegration:
    """Insert or update the tenant's encrypted credentials (sync)."""
    stmt = pg_insert(TenantIntegration).values(
        tenant_id=tenant_id,
        provider="ramp",
        encrypted_access_token=encrypted_access_token,
        encrypted_refresh_token=encrypted_refresh_token,
        encryption_nonce=encryption_nonce,
        token_expires_at=token_expires_at,
        connection_status=ConnectionStatus.ACTIVE,
        scopes=scopes or [],
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["tenant_id"],
        set_={
            "encrypted_access_token": stmt.excluded.encrypted_access_token,
            "encrypted_refresh_token": stmt.excluded.encrypted_refresh_token,
            "encryption_nonce": stmt.excluded.encryption_nonce,
            "token_expires_at": stmt.excluded.token_expires_at,
            "connection_status": ConnectionStatus.ACTIVE,
            "scopes": stmt.excluded.scopes,
            "last_error": None,
        },
    )
    session.execute(stmt)
    row = session.execute(
        select(TenantIntegration).where(TenantIntegration.tenant_id == tenant_id)
    ).scalar_one()
    logger.info("integration_upserted", tenant_id=tenant_id)
    return row


async def aupsert_integration(
    session: AsyncSession,
    *,
    tenant_id: str,
    encrypted_access_token: bytes,
    encrypted_refresh_token: bytes,
    encryption_nonce: bytes,
    token_expires_at: datetime | None,
    scopes: list[str] | None = None,
) -> TenantIntegration:
    """Insert or update the tenant's encrypted credentials (async)."""
    stmt = pg_insert(TenantIntegration).values(
        tenant_id=tenant_id,
        provider="ramp",
        encrypted_access_token=encrypted_access_token,
        encrypted_refresh_token=encrypted_refresh_token,
        encryption_nonce=encryption_nonce,
        token_expires_at=token_expires_at,
        connection_status=ConnectionStatus.ACTIVE,
        scopes=scopes or [],
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["tenant_id"],
        set_={
            "encrypted_access_token": stmt.excluded.encrypted_access_token,
            "encrypted_refresh_token": stmt.excluded.encrypted_refresh_token,
            "encryption_nonce": stmt.excluded.encryption_nonce,
            "token_expires_at": stmt.excluded.token_expires_at,
            "connection_status": ConnectionStatus.ACTIVE,
            "scopes": stmt.excluded.scopes,
            "last_error": None,
        },
    )
    await session.execute(stmt)
    row = (
        await session.execute(
            select(TenantIntegration).where(TenantIntegration.tenant_id == tenant_id)
        )
    ).scalar_one()
    logger.info("integration_upserted", tenant_id=tenant_id)
    return row


async def acreate_pending_checkpoint(
    session: AsyncSession,
    *,
    tenant_id: str,
    entity: EntityType,
    mode: SyncMode,
    cursor_token: str | None = None,
    event_id: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> tuple[IngestionSyncCheckpoint, bool]:
    """Create a PENDING checkpoint idempotently.

    Returns ``(checkpoint, created)`` where ``created=False`` means a
    duplicate request mapped to an already-open checkpoint.
    """
    if event_id:
        existing = (
            await session.execute(
                select(IngestionSyncCheckpoint).where(IngestionSyncCheckpoint.event_id == event_id)
            )
        ).scalar_one_or_none()
        if existing is not None:
            logger.info("checkpoint_duplicate_event", tenant_id=tenant_id, event_id=event_id)
            return existing, False
    else:
        existing = (
            await session.execute(
                select(IngestionSyncCheckpoint)
                .where(
                    IngestionSyncCheckpoint.tenant_id == tenant_id,
                    IngestionSyncCheckpoint.entity_type == entity,
                    IngestionSyncCheckpoint.mode == mode,
                    IngestionSyncCheckpoint.status.in_([SyncStatus.PENDING, SyncStatus.RUNNING]),
                )
                .order_by(IngestionSyncCheckpoint.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if existing is not None:
            logger.info("checkpoint_duplicate_open", tenant_id=tenant_id, entity=entity.value)
            return existing, False

    checkpoint = IngestionSyncCheckpoint(
        sync_id=uuid.uuid4(),
        tenant_id=tenant_id,
        entity_type=entity,
        mode=mode,
        status=SyncStatus.PENDING,
        cursor_token=cursor_token,
        event_id=event_id,
        date_from=date_from,
        date_to=date_to,
        attempt_count=0,
    )
    session.add(checkpoint)
    await session.flush()
    logger.info(
        "checkpoint_created",
        tenant_id=tenant_id,
        entity=entity.value,
        mode=mode.value,
        sync_id=str(checkpoint.sync_id),
    )
    return checkpoint, True


def mark_checkpoint(
    session: Session,
    checkpoint: IngestionSyncCheckpoint,
    *,
    status: SyncStatus,
    cursor_token: str | None = None,
    error_log: str | None = None,
) -> None:
    """Transition a checkpoint (sync worker usage) with audit timestamps."""
    now = datetime.now(UTC)
    checkpoint.status = status
    if status == SyncStatus.RUNNING:
        checkpoint.attempt_count += 1
        if checkpoint.started_at is None:
            checkpoint.started_at = now
    if cursor_token is not None:
        checkpoint.cursor_token = cursor_token
    if status == SyncStatus.SUCCESS and checkpoint.cursor_token:
        checkpoint.last_success_cursor = checkpoint.cursor_token
    if error_log is not None:
        checkpoint.error_log = error_log[:4000]  # truncated, never secrets
    if status in (SyncStatus.SUCCESS, SyncStatus.FAILED):
        checkpoint.finished_at = now
    session.add(checkpoint)


async def amark_checkpoint(
    session: AsyncSession,
    checkpoint: IngestionSyncCheckpoint,
    *,
    status: SyncStatus,
    cursor_token: str | None = None,
    error_log: str | None = None,
) -> None:
    """Transition a checkpoint (async version) with audit timestamps."""
    now = datetime.now(UTC)
    checkpoint.status = status
    if status == SyncStatus.RUNNING:
        checkpoint.attempt_count += 1
        if checkpoint.started_at is None:
            checkpoint.started_at = now
    if cursor_token is not None:
        checkpoint.cursor_token = cursor_token
    if status == SyncStatus.SUCCESS and checkpoint.cursor_token:
        checkpoint.last_success_cursor = checkpoint.cursor_token
    if error_log is not None:
        checkpoint.error_log = error_log[:4000]
    if status in (SyncStatus.SUCCESS, SyncStatus.FAILED):
        checkpoint.finished_at = now
    session.add(checkpoint)
    await session.flush()