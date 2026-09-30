"""Initial schema: tenant_integrations + ingestion_sync_checkpoints.

Revision ID: 0001_initial
Revises: None
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute('CREATE EXTENSION IF NOT EXISTS "pgcrypto"')
    op.execute(
        "DO $$ BEGIN CREATE TYPE connection_status AS ENUM ('ACTIVE', 'EXPIRED', 'REVOKED'); EXCEPTION WHEN duplicate_object THEN NULL; END $$;"
    )
    op.execute(
        "DO $$ BEGIN CREATE TYPE sync_status AS ENUM ('PENDING', 'RUNNING', 'SUCCESS', 'FAILED'); EXCEPTION WHEN duplicate_object THEN NULL; END $$;"
    )
    op.execute(
        "DO $$ BEGIN CREATE TYPE entity_type AS ENUM ('card_transactions', 'bills', 'events'); EXCEPTION WHEN duplicate_object THEN NULL; END $$;"
    )
    op.execute(
        "DO $$ BEGIN CREATE TYPE sync_mode AS ENUM ('event_triggered', 'incremental', 'scheduled', 'backfill'); EXCEPTION WHEN duplicate_object THEN NULL; END $$;"
    )

    connection_status = postgresql.ENUM(
        "ACTIVE", "EXPIRED", "REVOKED", name="connection_status", create_type=False
    )
    sync_status = postgresql.ENUM(
        "PENDING", "RUNNING", "SUCCESS", "FAILED", name="sync_status", create_type=False
    )
    entity_type = postgresql.ENUM(
        "card_transactions", "bills", "events", name="entity_type", create_type=False
    )
    sync_mode = postgresql.ENUM(
        "event_triggered",
        "incremental",
        "scheduled",
        "backfill",
        name="sync_mode",
        create_type=False,
    )

    op.create_table(
        "tenant_integrations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", sa.String(128), unique=True, nullable=False, index=True),
        sa.Column("provider", sa.String(64), nullable=False, server_default="ramp"),
        sa.Column("encrypted_access_token", sa.LargeBinary, nullable=False),
        sa.Column("encrypted_refresh_token", sa.LargeBinary, nullable=False),
        sa.Column("encryption_nonce", sa.LargeBinary, nullable=False),
        sa.Column("token_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("connection_status", connection_status, nullable=False, server_default="ACTIVE"),
        sa.Column("scopes", sa.JSON, nullable=True),
        sa.Column("last_error", sa.Text, nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_table(
        "ingestion_sync_checkpoints",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "sync_id", postgresql.UUID(as_uuid=True), unique=True, nullable=False, index=True
        ),
        sa.Column("tenant_id", sa.String(128), nullable=False, index=True),
        sa.Column("entity_type", entity_type, nullable=False),
        sa.Column("mode", sync_mode, nullable=False, server_default="incremental"),
        sa.Column("status", sync_status, nullable=False, server_default="PENDING", index=True),
        sa.Column("cursor_token", sa.Text, nullable=True),
        sa.Column("last_success_cursor", sa.Text, nullable=True),
        sa.Column("event_id", sa.String(256), nullable=True),
        sa.Column("date_from", sa.String(32), nullable=True),
        sa.Column("date_to", sa.String(32), nullable=True),
        sa.Column("error_log", sa.Text, nullable=True),
        sa.Column("attempt_count", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("event_id", name="uq_checkpoints_event_id"),
    )
    op.create_index(
        "ix_checkpoints_tenant_entity_status",
        "ingestion_sync_checkpoints",
        ["tenant_id", "entity_type", "status"],
    )


def downgrade() -> None:
    op.drop_index("ix_checkpoints_tenant_entity_status", table_name="ingestion_sync_checkpoints")
    op.drop_table("ingestion_sync_checkpoints")
    op.drop_table("tenant_integrations")
    op.execute("DROP TYPE IF EXISTS sync_mode")
    op.execute("DROP TYPE IF EXISTS entity_type")
    op.execute("DROP TYPE IF EXISTS sync_status")
    op.execute("DROP TYPE IF EXISTS connection_status")
