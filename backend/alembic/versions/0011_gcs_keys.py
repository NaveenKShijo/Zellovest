"""Rename S3 key columns to GCS (GCP-only storage).

Revision ID: 0011_gcs_keys
Revises: 0010_merge_heads

Renames ``documents.s3_key`` → ``documents.gcs_key`` (plus its unique
constraint) and ``card_transactions.raw_s3_key`` → ``raw_gcs_key`` to match
the GCS-only bronze lake (``gcs_writer`` / direct-to-GCS uploads).
"""

from alembic import op

revision = "0011_gcs_keys"
down_revision = "0010_merge_heads"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE documents RENAME COLUMN s3_key TO gcs_key")
    op.execute(
        "ALTER TABLE documents RENAME CONSTRAINT "
        "uq_documents_s3_key TO uq_documents_gcs_key"
    )
    op.execute("ALTER TABLE card_transactions RENAME COLUMN raw_s3_key TO raw_gcs_key")


def downgrade() -> None:
    op.execute("ALTER TABLE card_transactions RENAME COLUMN raw_gcs_key TO raw_s3_key")
    op.execute(
        "ALTER TABLE documents RENAME CONSTRAINT "
        "uq_documents_gcs_key TO uq_documents_s3_key"
    )
    op.execute("ALTER TABLE documents RENAME COLUMN gcs_key TO s3_key")
