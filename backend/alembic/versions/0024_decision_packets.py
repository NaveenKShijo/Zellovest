"""Create decision_packets table for pre-computed procurement outcomes.

Revision ID: 0024_decision_packets
Revises: 0023_seat_forecast_horizon_and_mlops
Create Date: 2026-11-27
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0024_decision_packets"
down_revision = "0023_seat_forecast_horizon_and_mlops"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create decision_packets table and supporting indexes."""
    op.create_table(
        "decision_packets",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", sa.String(128), nullable=False),
        sa.Column("packet_type", sa.String(32), nullable=False),
        sa.Column("entity_type", sa.String(32), nullable=False),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("vendor_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("title", sa.String(256), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("recommended_action", sa.Text(), nullable=True),
        sa.Column("financial_impact", sa.Numeric(14, 2), nullable=True),
        sa.Column("currency", sa.String(8), nullable=False, server_default="USD"),
        sa.Column("urgency_date", sa.Date(), nullable=True),
        sa.Column("source_hash", sa.String(64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column(
            "status", sa.String(32), nullable=False, server_default="pending_review"
        ),
        sa.Column("actioned_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("actioned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "packet_type",
            "entity_id",
            name="uq_decision_packet_tenant_type_entity",
        ),
    )
    op.create_index("ix_decision_packets_tenant_id", "decision_packets", ["tenant_id"])
    op.create_index("ix_dp_tenant_status", "decision_packets", ["tenant_id", "status"])
    op.create_index("ix_dp_tenant_type", "decision_packets", ["tenant_id", "packet_type"])
    op.create_index("ix_dp_tenant_urgency", "decision_packets", ["tenant_id", "urgency_date"])
    op.create_index("ix_dp_tenant_vendor", "decision_packets", ["tenant_id", "vendor_id"])


def downgrade() -> None:
    """Drop decision_packets table and indexes."""
    op.drop_index("ix_dp_tenant_vendor", table_name="decision_packets")
    op.drop_index("ix_dp_tenant_urgency", table_name="decision_packets")
    op.drop_index("ix_dp_tenant_type", table_name="decision_packets")
    op.drop_index("ix_dp_tenant_status", table_name="decision_packets")
    op.drop_index("ix_decision_packets_tenant_id", table_name="decision_packets")
    op.drop_table("decision_packets")
