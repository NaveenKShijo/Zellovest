"""Persist LLM-judge RAG evaluation scores without question or answer text."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0017_rag_evaluation_results"
down_revision = "0016_contract_version_lineage"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create tenant-scoped evaluation result records."""
    op.create_table(
        "rag_evaluation_results",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", sa.String(128), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("evaluator_model", sa.String(256), nullable=False),
        sa.Column("question_hash", sa.String(64), nullable=False),
        sa.Column("source_document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("scores", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                  nullable=False),
        sa.UniqueConstraint("tenant_id", "run_id", "question_hash",
                            name="uq_rag_eval_run_question"),
    )
    op.create_index("ix_rag_evaluation_results_tenant_id", "rag_evaluation_results", ["tenant_id"])
    op.create_index("ix_rag_eval_tenant_created", "rag_evaluation_results",
                    ["tenant_id", "created_at"])


def downgrade() -> None:
    """Drop stored evaluation result records."""
    op.drop_index("ix_rag_eval_tenant_created", table_name="rag_evaluation_results")
    op.drop_index("ix_rag_evaluation_results_tenant_id", table_name="rag_evaluation_results")
    op.drop_table("rag_evaluation_results")
