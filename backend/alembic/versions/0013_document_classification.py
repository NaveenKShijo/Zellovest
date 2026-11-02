"""Extraction artifact persistence + Stage-2 classification columns.

Adds:
- ``extraction_artifacts`` table: one row per processed upload storing
  queryable extraction metadata (PRD §27.5.4 "PostgreSQL artifacts
  metadata") plus the first ~4k chars of extracted text as the Stage-2
  Jev classification working set. The bulky payload lives in GCS.
- ``uploads.document_type_confidence`` / ``uploads.classification_method``:
  Stage-2 output home (doc_type already exists on the row).

Revision ID: 0013_document_classification
Revises: 0012_password_reset_tokens
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from alembic import op

revision = "0013_document_classification"
down_revision = "0012_password_reset_tokens"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create extraction_artifacts and add classification output columns."""
    op.create_table(
        "extraction_artifacts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", sa.String(128), nullable=False),
        sa.Column(
            "upload_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("uploads.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source_gcs_key", sa.Text(), nullable=False),
        sa.Column("artifact_gcs_key", sa.Text(), nullable=True),
        sa.Column("route", sa.String(32), nullable=True),
        sa.Column("file_type", sa.String(32), nullable=True),
        sa.Column("text_chars", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("extraction_method", sa.String(64), nullable=False, server_default="unknown"),
        sa.Column("extraction_confidence", sa.Numeric(5, 4), nullable=True),
        sa.Column("text_snippet", sa.Text(), nullable=False, server_default=""),
        sa.Column("classification", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("upload_id", name="uq_extraction_artifacts_upload_id"),
    )
    op.create_index(
        "ix_extraction_artifacts_tenant_id", "extraction_artifacts", ["tenant_id"]
    )
    op.add_column(
        "uploads",
        sa.Column("document_type_confidence", sa.Numeric(5, 4), nullable=True),
    )
    op.add_column(
        "uploads",
        sa.Column("classification_method", sa.String(32), nullable=True),
    )


def downgrade() -> None:
    """Drop extraction_artifacts and the classification output columns."""
    op.drop_column("uploads", "classification_method")
    op.drop_column("uploads", "document_type_confidence")
    op.drop_index(
        "ix_extraction_artifacts_tenant_id", table_name="extraction_artifacts"
    )
    op.drop_table("extraction_artifacts")
