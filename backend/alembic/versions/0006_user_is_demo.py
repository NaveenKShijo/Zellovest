"""Demo-account flag on users (sandbox explores, cannot invite).

Revision ID: 0006_user_is_demo
Revises: 0005_invitations
"""

import sqlalchemy as sa
from alembic import op

revision = "0006_user_is_demo"
down_revision = "0005_invitations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("is_demo", sa.Boolean(), nullable=False, server_default="false"))


def downgrade() -> None:
    op.drop_column("users", "is_demo")
