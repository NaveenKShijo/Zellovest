"""Merge parallel heads: demo flag + foundation/transact/intelligence/nonce.

Revision ID: 0010_merge_heads
Revises: 0006_user_is_demo, 0009_refresh_nonce

Both branches only add (columns, tables, FK references to users.id) and
touch no common objects, so the merge itself performs no operations.
"""

revision = "0010_merge_heads"
down_revision = ("0006_user_is_demo", "0009_refresh_nonce")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
