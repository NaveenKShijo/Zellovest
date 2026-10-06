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

from alembic import op

revision = "0002_drive_provider"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # (tenant_id, provider) uniqueness: one row per provider per tenant.
    op.drop_constraint(
        "tenant_integrations_tenant_id_key", "tenant_integrations", type_="unique"
    )
    op.create_index(
        "ix_tenant_integrations_tenant_id", "tenant_integrations", ["tenant_id"]
    )
    op.create_unique_constraint(
        "uq_integrations_tenant_provider",
        "tenant_integrations",
        ["tenant_id", "provider"],
    )
    # Enum values for document pull-sync checkpoints. ALTER TYPE ... ADD VALUE
    # cannot run inside a transaction block, so use AUTOCOMMIT.
    bind = op.get_bind()
    with bind.execution_options(isolation_level="AUTOCOMMIT").connect() as conn:
        for value in ("invoices", "contracts", "documents"):
            conn.execute(
                sa.text(
                    f"ALTER TYPE entity_type ADD VALUE IF NOT EXISTS '{value}'"
                )
            )


def downgrade() -> None:
    op.drop_constraint(
        "uq_integrations_tenant_provider", "tenant_integrations", type_="unique"
    )
    op.drop_index("ix_tenant_integrations_tenant_id", table_name="tenant_integrations")
    # NOTE: re-adding the single-column unique fails if a tenant holds more
    # than one provider row; resolve duplicates before downgrading.
    op.create_unique_constraint(
        "tenant_integrations_tenant_id_key",
        "tenant_integrations",
        ["tenant_id"],
    )
