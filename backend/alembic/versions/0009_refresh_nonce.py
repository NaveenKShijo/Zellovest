"""Per-token GCM nonces for stored OAuth credentials.

Revision ID: 0009_refresh_nonce
Revises: 0008_intelligence

Background: callbacks encrypted the access and refresh tokens with two
independently generated nonces but stored only the access token's nonce
(the refresh call's nonce was discarded). The refresh ciphertext was
therefore undecryptable, so no new access token could be minted once the
old one expired without a manual Reconnect.

Change:
- ``RENAME COLUMN encryption_nonce TO access_nonce`` (name now states
  which ciphertext the nonce belongs to; guarded so re-runs are safe).
- ``ADD COLUMN refresh_nonce BYTEA NULL``. New connects/refreshes persist
  both nonces (runtime call sites updated alongside). Pre-0009 rows keep
  ``refresh_nonce = NULL`` — their refresh tokens remain unrecoverable and
  those tenants Reconnect on next expiry (natural rotation, no forced
  expiry).
"""

from alembic import op

revision = "0009_refresh_nonce"
down_revision = "0008_intelligence"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "DO $$ BEGIN "
        "IF EXISTS (SELECT 1 FROM information_schema.columns "
        "WHERE table_name = 'tenant_integrations' "
        "AND column_name = 'encryption_nonce') "
        "AND NOT EXISTS (SELECT 1 FROM information_schema.columns "
        "WHERE table_name = 'tenant_integrations' "
        "AND column_name = 'access_nonce') THEN "
        "ALTER TABLE tenant_integrations "
        "RENAME COLUMN encryption_nonce TO access_nonce; "
        "END IF; END $$;"
    )
    op.execute("ALTER TABLE tenant_integrations ADD COLUMN IF NOT EXISTS refresh_nonce BYTEA")


def downgrade() -> None:
    op.execute("ALTER TABLE tenant_integrations DROP COLUMN IF EXISTS refresh_nonce")
    op.execute(
        "DO $$ BEGIN "
        "IF EXISTS (SELECT 1 FROM information_schema.columns "
        "WHERE table_name = 'tenant_integrations' "
        "AND column_name = 'access_nonce') "
        "AND NOT EXISTS (SELECT 1 FROM information_schema.columns "
        "WHERE table_name = 'tenant_integrations' "
        "AND column_name = 'encryption_nonce') THEN "
        "ALTER TABLE tenant_integrations "
        "RENAME COLUMN access_nonce TO encryption_nonce; "
        "END IF; END $$;"
    )
