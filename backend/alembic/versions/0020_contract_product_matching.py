"""Derive Maverick approved-product matches from active contract terms.

Revision ID: 0020_contract_product_matching
Revises: 0019_maverick_spend_enhancements
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0020_contract_product_matching"
down_revision = "0019_maverick_spend_enhancements"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add cached contract-product profiles and alert lineage references."""
    op.create_table(
        "contract_product_profiles",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", sa.String(128), nullable=False),
        sa.Column("contract_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("contracts.id"), nullable=False),
        sa.Column("contract_line_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("contract_lines.id"), nullable=False),
        sa.Column(
            "contract_term_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("contract_terms_versioned.id"),
            nullable=False,
        ),
        sa.Column("vendor_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("vendors.id"), nullable=False),
        sa.Column("source_fingerprint", sa.String(64), nullable=False),
        sa.Column("product_name", sa.String(256), nullable=False),
        sa.Column("category", sa.String(128), nullable=True),
        sa.Column("capabilities", sa.JSON(), nullable=True),
        sa.Column("use_cases", sa.JSON(), nullable=True),
        sa.Column("capability_text", sa.Text(), nullable=False),
        sa.Column("is_saas", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("raw_response", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "contract_line_id", name="uq_contract_product_profile_line"),
    )
    op.create_index("ix_contract_product_profiles_tenant", "contract_product_profiles", ["tenant_id"])
    op.add_column("maverick_alerts", sa.Column("overlap_contract_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("maverick_alerts", sa.Column("overlap_contract_term_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        "fk_maverick_alerts_overlap_contract",
        "maverick_alerts",
        "contracts",
        ["overlap_contract_id"],
        ["id"],
    )
    op.create_foreign_key(
        "fk_maverick_alerts_overlap_contract_term",
        "maverick_alerts",
        "contract_terms_versioned",
        ["overlap_contract_term_id"],
        ["id"],
    )


def downgrade() -> None:
    """Remove contract-product semantic matching storage."""
    op.drop_constraint("fk_maverick_alerts_overlap_contract_term", "maverick_alerts", type_="foreignkey")
    op.drop_constraint("fk_maverick_alerts_overlap_contract", "maverick_alerts", type_="foreignkey")
    op.drop_column("maverick_alerts", "overlap_contract_term_id")
    op.drop_column("maverick_alerts", "overlap_contract_id")
    op.drop_index("ix_contract_product_profiles_tenant", table_name="contract_product_profiles")
    op.drop_table("contract_product_profiles")
