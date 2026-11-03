"""Persist pending and committed human contract reviews.

Revision ID: 0014_human_contract_review
Revises: 0013_document_classification
"""

import sqlalchemy as sa
from alembic import op

revision = "0014_human_contract_review"
down_revision = "0013_document_classification"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add review state and permit multiple terms within a contract version."""
    # Multiple product lines in one contract may share the same effective
    # period. Keep the overlap rule per line number so later versions of the
    # same line still cannot overlap their prior effective period.
    op.drop_constraint(
        "no_overlap_contract_terms",
        "contract_terms_versioned",
    )
    op.add_column(
        "contract_terms_versioned",
        sa.Column("line_no", sa.Integer(), nullable=False, server_default="1"),
    )
    op.drop_constraint(
        "uq_terms_tenant_contract_ver",
        "contract_terms_versioned",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_terms_tenant_contract_ver_line",
        "contract_terms_versioned",
        ["tenant_id", "contract_id", "version_no", "line_no"],
    )
    op.alter_column("contract_terms_versioned", "line_no", server_default=None)
    op.execute(
        "ALTER TABLE contract_terms_versioned ADD CONSTRAINT "
        "no_overlap_contract_terms EXCLUDE USING gist "
        "(contract_id WITH =, line_no WITH =, "
        "daterange(effective_from, COALESCE(effective_to, 'infinity'::date)) WITH &&)"
    )
    op.add_column(
        "extraction_artifacts",
        sa.Column("review_status", sa.String(length=16), nullable=True),
    )
    op.add_column(
        "extraction_artifacts",
        sa.Column("review_data", sa.JSON(), nullable=True),
    )
    op.create_index(
        "ix_extraction_artifacts_review_status",
        "extraction_artifacts",
        ["review_status"],
    )


def downgrade() -> None:
    """Remove human review columns and restore one term per version."""
    op.drop_index(
        "ix_extraction_artifacts_review_status",
        table_name="extraction_artifacts",
    )
    op.drop_column("extraction_artifacts", "review_data")
    op.drop_column("extraction_artifacts", "review_status")
    op.drop_constraint(
        "no_overlap_contract_terms",
        "contract_terms_versioned",
    )
    op.drop_constraint(
        "uq_terms_tenant_contract_ver_line",
        "contract_terms_versioned",
        type_="unique",
    )
    op.drop_column("contract_terms_versioned", "line_no")
    op.create_unique_constraint(
        "uq_terms_tenant_contract_ver",
        "contract_terms_versioned",
        ["tenant_id", "contract_id", "version_no"],
    )
    op.execute(
        "ALTER TABLE contract_terms_versioned ADD CONSTRAINT "
        "no_overlap_contract_terms EXCLUDE USING gist "
        "(contract_id WITH =, "
        "daterange(effective_from, COALESCE(effective_to, 'infinity'::date)) WITH &&)"
    )
