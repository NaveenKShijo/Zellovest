"""Provider-aware integrations: (tenant_id, provider) unique + documents entity.

Revision ID: 0002_drive_provider
Revises: 0001_initial

- ``tenant_integrations``: replace the single-column unique on ``tenant_id``
  with a composite unique on (``tenant_id``, ``provider``) so one
  single-tenant deployment can hold both ``ramp`` and ``google_drive``
  credentials side by side.
- ``entity_type`` enum: add the ``documents`` value used by Google Drive
  pull-sync checkpoints (``invoices``/``contracts`` are model-declared and
  added here too for consistency).
"""

import sqlalchemy as sa
from sqlalchemy import create_engine

from alembic import op

revision = "0002_drive_provider"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def _add_enum_values(type_name: str, values: tuple[str, ...]) -> None:
    """Add values to a PG enum outside the migration transaction.

    Opens a dedicated AUTOCOMMIT connection from the same database URL
    as the migration bind (normalising any async driver to psycopg).
    """
    url = op.get_bind().engine.url.render_as_string(hide_password=False).replace(
        "+asyncpg", "+psycopg"
    )
    engine = create_engine(url, isolation_level="AUTOCOMMIT")
    try:
        with engine.connect() as conn:
            for value in values:
                conn.execute(
                    sa.text(f"ALTER TYPE {type_name} ADD VALUE IF NOT EXISTS '{value}'")
                )
    finally:
        engine.dispose()


def upgrade() -> None:
    # (tenant_id, provider) uniqueness: one row per provider per tenant.
    # NOTE (0001 emitted-unique-index fix): 0001 declares tenant_id with
    # unique=True AND index=True, which SQLAlchemy collapses into a single
    # UNIQUE *index* (ix_tenant_integrations_tenant_id) — no standalone
    # UNIQUE *constraint* named tenant_integrations_tenant_id_key is ever
    # created. The DROP CONSTRAINT below is therefore only an IF EXISTS
    # guard for DBs built by other means; the real uniqueness to remove
    # is the unique index, replaced here by a plain lookup index.
    op.execute("ALTER TABLE tenant_integrations DROP CONSTRAINT IF EXISTS tenant_integrations_tenant_id_key")
    op.execute("DROP INDEX IF EXISTS ix_tenant_integrations_tenant_id")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_tenant_integrations_tenant_id "
        "ON tenant_integrations (tenant_id)"
    )
    # Postgres has no ADD CONSTRAINT IF NOT EXISTS, so guard via catalog.
    op.execute(
        "DO $$ BEGIN "
        "IF NOT EXISTS (SELECT 1 FROM pg_constraint "
        "WHERE conname = 'uq_integrations_tenant_provider') THEN "
        "ALTER TABLE tenant_integrations ADD CONSTRAINT "
        "uq_integrations_tenant_provider UNIQUE (tenant_id, provider); "
        "END IF; END $$;"
    )
    # Enum values for document pull-sync checkpoints. ALTER TYPE ... ADD VALUE
    # cannot run inside a transaction block, and env.py wraps all revisions
    # in one begin_transaction() — so this must use a dedicated AUTOCOMMIT
    # connection, not the alembic bind (whose transaction is already open
    # after the statements above).
    _add_enum_values("entity_type", ("invoices", "contracts", "documents"))


def downgrade() -> None:
    # NOTE: re-adding single-tenant uniqueness fails if a tenant holds more
    # than one provider row; resolve duplicates before downgrading.
    # Restores the actual 0001 state: a UNIQUE *index* (0001's unique=True +
    # index=True never emitted a standalone UNIQUE constraint).
    op.execute(
        "ALTER TABLE tenant_integrations "
        "DROP CONSTRAINT IF EXISTS uq_integrations_tenant_provider"
    )
    op.execute("DROP INDEX IF EXISTS ix_tenant_integrations_tenant_id")
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_tenant_integrations_tenant_id "
        "ON tenant_integrations (tenant_id)"
    )
