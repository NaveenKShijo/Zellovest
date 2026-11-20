"""Add Ask AI conversation and message persistence.

Revision ID: 0021_ask_ai_conversations
Revises: 0020_contract_product_matching
Create Date: 2026-11-20

The Agentic Reasoning Service owns conversation state (PRD 22-24). These
tables store the user question, the rendered answer, and the structured
citations/evidence/tool traces/proposed actions used to produce it so a
reload or audit replay can reconstruct the exchange exactly.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0021_ask_ai_conversations"
down_revision = "0020_contract_product_matching"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create Ask AI conversation and message tables."""
    op.create_table(
        "ask_ai_conversations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", sa.String(128), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("title", sa.String(256), nullable=False, server_default="Untitled conversation"),
        sa.Column("context", sa.JSON(), nullable=True),
        sa.Column("message_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_message_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_ask_ai_conversations_tenant_id", "ask_ai_conversations", ["tenant_id"])
    op.create_index("ix_ask_ai_conversations_user_id", "ask_ai_conversations", ["user_id"])
    op.create_index(
        "ix_ask_ai_conv_tenant_user", "ask_ai_conversations", ["tenant_id", "user_id"]
    )
    op.create_index(
        "ix_ask_ai_conv_tenant_last", "ask_ai_conversations", ["tenant_id", "last_message_at"]
    )

    op.create_table(
        "ask_ai_messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "conversation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("ask_ai_conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("tenant_id", sa.String(128), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False, server_default=""),
        sa.Column("correlation_id", sa.Text(), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_ask_ai_messages_conversation_id", "ask_ai_messages", ["conversation_id"])
    op.create_index("ix_ask_ai_messages_tenant_id", "ask_ai_messages", ["tenant_id"])
    op.create_index(
        "ix_ask_ai_msg_conversation_time", "ask_ai_messages", ["conversation_id", "created_at"]
    )
    op.create_index(
        "ix_ask_ai_msg_tenant_corr", "ask_ai_messages", ["tenant_id", "correlation_id"]
    )


def downgrade() -> None:
    """Drop Ask AI conversation storage."""
    op.drop_index("ix_ask_ai_msg_tenant_corr", table_name="ask_ai_messages")
    op.drop_index("ix_ask_ai_msg_conversation_time", table_name="ask_ai_messages")
    op.drop_index("ix_ask_ai_messages_tenant_id", table_name="ask_ai_messages")
    op.drop_index("ix_ask_ai_messages_conversation_id", table_name="ask_ai_messages")
    op.drop_table("ask_ai_messages")
    op.drop_index("ix_ask_ai_conv_tenant_last", table_name="ask_ai_conversations")
    op.drop_index("ix_ask_ai_conv_tenant_user", table_name="ask_ai_conversations")
    op.drop_index("ix_ask_ai_conversations_user_id", table_name="ask_ai_conversations")
    op.drop_index("ix_ask_ai_conversations_tenant_id", table_name="ask_ai_conversations")
    op.drop_table("ask_ai_conversations")
