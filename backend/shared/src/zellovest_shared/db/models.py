"""PostgreSQL metadata/credential schema (SQLAlchemy 2.0 typed ORM).

Tables:
- ``tenant_integrations``: AES-256-GCM encrypted OAuth tokens per tenant.
- ``ingestion_sync_checkpoints``: sync execution state + pagination cursors.

Single-tenant isolation: each deployment owns its database; ``tenant_id``
uniqueness guards against duplicate rows within the instance.
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
    """Encrypted OAuth credentials for one tenant deployment."""

    __tablename__ = "tenant_integrations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)
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
