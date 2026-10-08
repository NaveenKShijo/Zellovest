"""Upload staging leases for direct-to-GCS flow.

Revision ID: 0003_uploads
Revises: 0002_drive_provider
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from alembic import op

revision = "0003_uploads"
down_revision = "0002_drive_provider"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "DO $$ BEGIN CREATE TYPE upload_status AS ENUM "
        "('pending','staged','processing','completed','failed'); "
        "EXCEPTION WHEN duplicate_object THEN NULL; END $$;"
    )
    upload_status = postgresql.ENUM(
        "pending", "staged", "processing", "completed", "failed",
        name="upload_status", create_type=False,
    )
    op.create_table(
        "uploads",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", sa.String(128), nullable=False, index=True),
        sa.Column("vendor_id", sa.String(128), nullable=True, index=True),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("gcs_key", sa.Text, nullable=False),
        sa.Column("mime_type", sa.String(128), nullable=False),
        sa.Column("size_expected", sa.BigInteger, nullable=False),
        sa.Column("document_type", sa.String(32), nullable=False, server_default="other"),
        sa.Column("status", upload_status, nullable=False,
                  server_default="pending", index=True),
        sa.Column("error", sa.Text, nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("gcs_key", name="uq_uploads_gcs_key"),
    )
    op.create_index("ix_uploads_tenant_status", "uploads", ["tenant_id", "status"])


def downgrade() -> None:
    op.drop_index("ix_uploads_tenant_status", table_name="uploads")
    op.drop_table("uploads")
    op.execute("DROP TYPE IF EXISTS upload_status")
