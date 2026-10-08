"""PostgreSQL metadata/credential schema (SQLAlchemy 2.0 typed ORM).

Tables:
- ``tenant_integrations``: AES-256-GCM encrypted OAuth tokens per tenant.
- ``ingestion_sync_checkpoints``: sync execution state + pagination cursors.

Single-tenant isolation: each deployment owns its database; the
(``tenant_id``, ``provider``) uniqueness guards against duplicate rows
within the instance.
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    Enum,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from zellovest_shared.db.base import Base


class ConnectionStatus(str, enum.Enum):
    """OAuth connection lifecycle state."""

    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class SyncStatus(str, enum.Enum):
    """Sync execution state machine."""

    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"


class EntityType(str, enum.Enum):
    """External entity under ingestion."""

    CARD_TRANSACTIONS = "card_transactions"
    BILLS = "bills"
    EVENTS = "events"
    INVOICES = "invoices"
    CONTRACTS = "contracts"
    DOCUMENTS = "documents"


class SyncMode(str, enum.Enum):
    """How the sync was triggered."""

    EVENT_TRIGGERED = "event_triggered"
    INCREMENTAL = "incremental"
    SCHEDULED = "scheduled"
    BACKFILL = "backfill"


class TenantIntegration(Base):
    """Encrypted OAuth credentials for one tenant deployment.

    One row per (tenant, provider): ``tenant_id`` alone is NOT unique so a
    single-tenant deployment can hold both ``ramp`` and ``google_drive``
    credentials side by side (see ``uq_integrations_tenant_provider``).
    """

    __tablename__ = "tenant_integrations"
    __table_args__ = (
        UniqueConstraint("tenant_id", "provider", name="uq_integrations_tenant_provider"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(64), nullable=False, default="ramp")
    encrypted_access_token: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    encrypted_refresh_token: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    # 12-byte GCM nonce stored alongside ciphertext
    encryption_nonce: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    token_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    connection_status: Mapped[ConnectionStatus] = mapped_column(
        Enum(ConnectionStatus, name="connection_status"),
        nullable=False,
        default=ConnectionStatus.ACTIVE,
    )
    scopes: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class IngestionSyncCheckpoint(Base):
    """Sync execution checkpoint with cursor pagination and audit trail."""

    __tablename__ = "ingestion_sync_checkpoints"
    __table_args__ = (UniqueConstraint("event_id", name="uq_checkpoints_event_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    sync_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), unique=True, nullable=False, default=uuid.uuid4, index=True
    )
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    entity_type: Mapped[EntityType] = mapped_column(
        Enum(EntityType, name="entity_type", values_callable=lambda x: [e.value for e in x]),
        nullable=False,
    )
    mode: Mapped[SyncMode] = mapped_column(
        Enum(SyncMode, name="sync_mode", values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        default=SyncMode.INCREMENTAL,
    )
    status: Mapped[SyncStatus] = mapped_column(
        Enum(SyncStatus, name="sync_status"), nullable=False, default=SyncStatus.PENDING, index=True
    )
    cursor_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_success_cursor: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Webhook idempotency: external event id; NULL for polling/manual syncs.
    event_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    date_from: Mapped[str | None] = mapped_column(String(32), nullable=True)
    date_to: Mapped[str | None] = mapped_column(String(32), nullable=True)
    error_log: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempt_count: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class UploadStatus(enum.StrEnum):
    """Manual-upload staging lifecycle for direct-to-GCS flow."""

    PENDING = "pending"        # init signed, PUT not yet verified
    STAGED = "staged"          # complete verified, Celery enqueued
    PROCESSING = "processing"  # worker picked up
    COMPLETED = "completed"
    FAILED = "failed"


class Upload(Base):
    """Staging lease for one direct-to-GCS manual upload.

    One row per file: frontend calls one ``POST /uploads/init`` per
    ``File`` (see ``UploadProvider.tsx``), so 10 simultaneous drops =
    10 rows, no locking — uniqueness comes from server-generated
    ``id`` + ``gcs_key`` (uuid embedded in path).
    ``complete`` must look up this row and use *its* ``gcs_key``/
    ``tenant_id`` — never a client-supplied key.
    """

    __tablename__ = "uploads"
    __table_args__ = (
        UniqueConstraint("gcs_key", name="uq_uploads_gcs_key"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    vendor_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    gcs_key: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    mime_type: Mapped[str] = mapped_column(String(128), nullable=False)
    size_expected: Mapped[int] = mapped_column(BigInteger, nullable=False)
    document_type: Mapped[str] = mapped_column(String(32), nullable=False, default="other")
    status: Mapped[UploadStatus] = mapped_column(
        Enum(UploadStatus, name="upload_status",
             values_callable=lambda x: [e.value for e in x]),
        nullable=False, default=UploadStatus.PENDING, index=True,
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        server_default=func.now(), onupdate=func.now(),
    )
