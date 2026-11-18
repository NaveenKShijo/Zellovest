"""Add merchant_profiles table and maverick_alerts decision evidence columns.

Revision ID: 0019_maverick_spend_enhancements
Revises: 0018_remove_legacy_line_no
Create Date: 2026-11-14
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0019_maverick_spend_enhancements"
down_revision = "0018_remove_legacy_line_no"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create merchant_profiles table and add decision evidence to maverick_alerts."""
    op.create_table(
        "merchant_profiles",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", sa.String(128), nullable=False),
        sa.Column("merchant_name", sa.String(256), nullable=False),
        sa.Column("canonical_name", sa.String(256), nullable=True),
        sa.Column("domain", sa.String(256), nullable=True),
        sa.Column("product_name", sa.String(256), nullable=True),
        sa.Column("category", sa.String(128), nullable=True),
        sa.Column("capabilities", sa.JSON(), nullable=True),
        sa.Column("use_cases", sa.JSON(), nullable=True),
        sa.Column("is_saas", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("raw_response", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("tenant_id", "merchant_name", name="uq_merchant_profiles_tenant_name"),
    )
    op.create_index("ix_merch_prof_tenant", "merchant_profiles", ["tenant_id"])

    op.add_column("maverick_alerts", sa.Column("decision_evidence", sa.JSON(), nullable=True))
    op.add_column("maverick_alerts", sa.Column("assessment_outcome", sa.String(64), nullable=True))
    op.create_index("ix_mav_tenant_txn", "maverick_alerts", ["tenant_id", "transaction_id"])


def downgrade() -> None:
    """Drop merchant_profiles table and revert maverick_alerts changes."""
    op.drop_index("ix_mav_tenant_txn", table_name="maverick_alerts")
    op.drop_column("maverick_alerts", "assessment_outcome")
    op.drop_column("maverick_alerts", "decision_evidence")
    op.drop_index("ix_merch_prof_tenant", table_name="merchant_profiles")
    op.drop_table("merchant_profiles")
