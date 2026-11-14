"""remove legacy_line_no from contract_lines"""

from alembic import op
import sqlalchemy as sa

revision = "0018_remove_legacy_line_no"
down_revision = "0017_rag_evaluation_results"
branch_labels = None
depends_on = None

def upgrade():
    op.drop_constraint("uq_contract_lines_legacy_no", "contract_lines", type_="unique")
    op.drop_column("contract_lines", "legacy_line_no")

def downgrade():
    op.add_column("contract_lines", sa.Column("legacy_line_no", sa.Integer(), nullable=True))
    op.create_unique_constraint("uq_contract_lines_legacy_no", "contract_lines", ["tenant_id", "contract_id", "legacy_line_no"])