"""Foundation tables: identity + dimensions (single-tenant, V2 DB-per-tenant ready).

Revision ID: 0006_foundation
Revises: 0005_invitations

Creates (see ``dbdiagram.dbml`` A. Foundation + ``shared/.../db/core.py``):
tenants, departments, locations, business_entities, merchants, employees,
vendors, ramp_cards, software_catalog.

Notes:
- ``tenant_id`` is indexed on every table, no physical FK to ``tenants``.
- ``departments.head_employee_id`` has NO database FK (create-order cycle
  with ``employees.department_id``); resolved in application code.
- Ramp/Okta external IDs are nullable + ``UNIQUE(tenant_id, ext_id)``.
- ``software_catalog.okta_app_id`` arrives without FK; 0008 adds the
  ``okta_apps`` table + FK constraint.
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0006_foundation"
down_revision = "0005_invitations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tenants",
        sa.Column("tenant_id", sa.String(128), primary_key=True),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="active"),
        sa.Column("kms_key_id", sa.Text, nullable=True),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                 nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                 nullable=False),
    )

    op.create_table(
        "departments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", sa.String(128), nullable=False, index=True),
        sa.Column("ramp_department_id", sa.Text, nullable=True),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("head_employee_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("ramp_created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                 nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                 nullable=False),
        sa.UniqueConstraint("tenant_id", "ramp_department_id",
                            name="uq_departments_tenant_ramp"),
    )
    op.create_index("ix_dept_tenant_name", "departments", ["tenant_id", "name"])

    op.create_table(
        "locations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", sa.String(128), nullable=False, index=True),
        sa.Column("ramp_location_id", sa.Text, nullable=True),
        sa.Column("name", sa.String(256), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                 nullable=False),
        sa.UniqueConstraint("tenant_id", "ramp_location_id", name="uq_locations_tenant_ramp"),
    )

    op.create_table(
        "business_entities",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", sa.String(128), nullable=False, index=True),
        sa.Column("ramp_entity_id", sa.Text, nullable=True),
        sa.Column("name", sa.String(256), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                 nullable=False),
        sa.UniqueConstraint("tenant_id", "ramp_entity_id", name="uq_bizent_tenant_ramp"),
    )

    op.create_table(
        "merchants",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", sa.String(128), nullable=False, index=True),
        sa.Column("ramp_merchant_id", sa.Text, nullable=True),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("merchant_url", sa.String(512), nullable=True),
        sa.Column("icon_url", sa.Text, nullable=True),
        sa.Column("sk_category_id", sa.Integer, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                 nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                 nullable=False),
        sa.UniqueConstraint("tenant_id", "ramp_merchant_id", name="uq_merchants_tenant_ramp"),
    )
    op.create_index("ix_merch_tenant_name", "merchants", ["tenant_id", "name"])

    op.create_table(
        "employees",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", sa.String(128), nullable=False, index=True),
        sa.Column("email", sa.String(256), nullable=False),
        sa.Column("display_name", sa.String(256), nullable=True),
        sa.Column("first_name", sa.String(128), nullable=True),
        sa.Column("last_name", sa.String(128), nullable=True),
        sa.Column("employee_code", sa.String(64), nullable=True),
        sa.Column("department_id", postgresql.UUID(as_uuid=True),
                 sa.ForeignKey("departments.id"), nullable=True),
        sa.Column("department_raw", sa.String(128), nullable=True),
        sa.Column("location_id", postgresql.UUID(as_uuid=True),
                 sa.ForeignKey("locations.id"), nullable=True),
        sa.Column("business_entity_id", postgresql.UUID(as_uuid=True),
                 sa.ForeignKey("business_entities.id"), nullable=True),
        sa.Column("manager_id", postgresql.UUID(as_uuid=True),
                 sa.ForeignKey("employees.id"), nullable=True),
        sa.Column("employment_status", sa.String(32), nullable=False, server_default="active"),
        sa.Column("ramp_user_id", sa.Text, nullable=True),
        sa.Column("ramp_role", sa.String(64), nullable=True),
        sa.Column("ramp_status", sa.String(64), nullable=True),
        sa.Column("okta_user_id", sa.Text, nullable=True),
        sa.Column("okta_status", sa.String(32), nullable=True),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ramp_created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("okta_created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("okta_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                 nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                 nullable=False),
        sa.UniqueConstraint("tenant_id", "email", name="uq_emp_tenant_email"),
        sa.UniqueConstraint("tenant_id", "ramp_user_id", name="uq_emp_tenant_ramp"),
        sa.UniqueConstraint("tenant_id", "okta_user_id", name="uq_emp_tenant_okta"),
    )
    op.create_index("ix_emp_tenant_dept", "employees", ["tenant_id", "department_id"])
    op.create_index("ix_emp_tenant_code", "employees", ["tenant_id", "employee_code"])

    op.create_table(
        "vendors",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", sa.String(128), nullable=False, index=True),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("domain", sa.String(256), nullable=True),
        sa.Column("category", sa.String(128), nullable=True),
        sa.Column("payment_terms", sa.Text, nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="active"),
        sa.Column("ramp_vendor_id", sa.Text, nullable=True),
        sa.Column("external_vendor_id", sa.String(128), nullable=True),
        sa.Column("merchant_id", postgresql.UUID(as_uuid=True),
                 sa.ForeignKey("merchants.id"), nullable=True),
        sa.Column("owner_employee_id", postgresql.UUID(as_uuid=True),
                 sa.ForeignKey("employees.id"), nullable=True),
        sa.Column("sk_category_id", sa.Integer, nullable=True),
        sa.Column("accounting_remote_ids", sa.JSON, nullable=True),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("ramp_created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ramp_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metadata", sa.JSON, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                 nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                 nullable=False),
        sa.UniqueConstraint("tenant_id", "name", name="uq_vendors_tenant_name"),
        sa.UniqueConstraint("tenant_id", "ramp_vendor_id", name="uq_vendors_tenant_ramp"),
    )
    op.create_index("ix_vendors_tenant_cat", "vendors", ["tenant_id", "category"])

    op.create_table(
        "ramp_cards",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", sa.String(128), nullable=False, index=True),
        sa.Column("ramp_card_id", sa.Text, nullable=True),
        sa.Column("employee_id", postgresql.UUID(as_uuid=True),
                 sa.ForeignKey("employees.id"), nullable=True),
        sa.Column("card_last4", sa.String(8), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                 nullable=False),
        sa.UniqueConstraint("tenant_id", "ramp_card_id", name="uq_rampcards_tenant_ramp"),
    )
    op.create_index("ix_cards_tenant_emp", "ramp_cards", ["tenant_id", "employee_id"])

    op.create_table(
        "software_catalog",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", sa.String(128), nullable=False, index=True),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("vendor_id", postgresql.UUID(as_uuid=True),
                 sa.ForeignKey("vendors.id"), nullable=True),
        sa.Column("okta_app_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("category", sa.String(128), nullable=True),
        sa.Column("capability_text", sa.Text, nullable=True),
        sa.Column("website", sa.String(256), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                 nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                 nullable=False),
        sa.UniqueConstraint("tenant_id", "name", name="uq_catalog_tenant_name"),
    )


def downgrade() -> None:
    op.drop_table("software_catalog")
    op.drop_index("ix_cards_tenant_emp", table_name="ramp_cards")
    op.drop_table("ramp_cards")
    op.drop_index("ix_vendors_tenant_cat", table_name="vendors")
    op.drop_table("vendors")
    op.drop_index("ix_emp_tenant_code", table_name="employees")
    op.drop_index("ix_emp_tenant_dept", table_name="employees")
    op.drop_table("employees")
    op.drop_index("ix_merch_tenant_name", table_name="merchants")
    op.drop_table("merchants")
    op.drop_table("business_entities")
    op.drop_table("locations")
    op.drop_index("ix_dept_tenant_name", table_name="departments")
    op.drop_table("departments")
    op.drop_table("tenants")
