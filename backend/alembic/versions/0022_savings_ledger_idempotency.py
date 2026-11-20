"""Make savings-source ledger writes idempotent.

Revision ID: 0022_savings_ledger_idempotency
Revises: 0021_ask_ai_conversations
Create Date: 2026-11-20
"""

from alembic import op


revision = "0022_savings_ledger_idempotency"
down_revision = "0021_ask_ai_conversations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Prevent duplicate ledger entries for the same source event."""
    op.create_unique_constraint(
        "uq_savings_ledger_source",
        "savings_ledger",
        ["tenant_id", "source_type", "source_id"],
    )


def downgrade() -> None:
    """Remove the source-event idempotency constraint."""
    op.drop_constraint("uq_savings_ledger_source", "savings_ledger", type_="unique")
