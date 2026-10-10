"""Intelligence + close-loop tables: Okta, outputs, actions.

Revision ID: 0008_intelligence
Revises: 0007_transact

Creates (see ``dbdiagram.dbml`` E-G + ``shared/.../db/intelligence.py``):
okta_apps, okta_groups, okta_group_memberships, license_assignments,
usage_events, reconciliation_exceptions, maverick_alerts, seat_forecasts,
workflows, savings_ledger, audit_events.

Also:
- Adds the deferred FK ``software_catalog.okta_app_id -> okta_apps.id``
  (column shipped constraint-free in 0006).
- Extends the ``entity_type`` enum with ramp/okta sync entities via a
  dedicated AUTOCOMMIT connection (``ALTER TYPE ... ADD VALUE`` cannot run
  inside the migration transaction; pattern copied from 0002).
"""

import sqlalchemy as sa
from sqlalchemy import create_engine
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0008_intelligence"
down_revision = "0007_transact"
branch_labels = None
depends_on = None


def _create_enum(type_name: str, values: tuple[str, ...]) -> None:
    labels = ", ".join(f"'{v}'" for v in values)
    op.execute(
        f"DO $$ BEGIN CREATE TYPE {type_name} AS ENUM ({labels}); "
        "EXCEPTION WHEN duplicate_object THEN NULL; END $$;"
    )


def _add_enum_values(type_name: str, values: tuple[str, ...]) -> None:
    """Add values to a PG enum on a dedicated AUTOCOMMIT connection."""
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
    _create_enum(
        "exception_rule",
        ("price", "quantity", "date", "discount", "tax", "freight", "payment_term",
         "missing_po"),
    )
    _create_enum("exception_status", ("open", "acknowledged", "resolved", "dismissed"))
    _create_enum("alert_status", ("open", "notified", "migrated", "dismissed"))
    _create_enum(
        "workflow_type",
        ("invoice_approval", "contract_review", "vendor_onboarding",
         "purchase_order_approval", "renewal_negotiation", "human_review"),
    )
    _create_enum(
        "workflow_status", ("pending", "in_progress", "approved", "rejected", "cancelled")
    )
    _create_enum("savings_kind", ("hard_cash", "avoidance"))
    _create_enum("savings_status", ("potential", "verified"))
    _create_enum("risk_class", ("read_only", "low_risk", "high_risk"))

    exception_rule = postgresql.ENUM(
        "price", "quantity", "date", "discount", "tax", "freight", "payment_term",
        "missing_po", name="exception_rule", create_type=False,
    )
    exception_status = postgresql.ENUM(
        "open", "acknowledged", "resolved", "dismissed",
        name="exception_status", create_type=False,
    )
    alert_status = postgresql.ENUM(
        "open", "notified", "migrated", "dismissed",
        name="alert_status", create_type=False,
    )
    workflow_type = postgresql.ENUM(
        "invoice_approval", "contract_review", "vendor_onboarding",
        "purchase_order_approval", "renewal_negotiation", "human_review",
        name="workflow_type", create_type=False,
    )
    workflow_status = postgresql.ENUM(
        "pending", "in_progress", "approved", "rejected", "cancelled",
        name="workflow_status", create_type=False,
    )
    savings_kind = postgresql.ENUM(
        "hard_cash", "avoidance", name="savings_kind", create_type=False
    )
    savings_status = postgresql.ENUM(
        "potential", "verified", name="savings_status", create_type=False
    )
    risk_class = postgresql.ENUM(
        "read_only", "low_risk", "high_risk", name="risk_class", create_type=False
    )

    op.create_table(
        "okta_apps",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", sa.String(128), nullable=False, index=True),
        sa.Column("okta_app_id", sa.Text, nullable=False),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("label", sa.String(256), nullable=True),
        sa.Column("status", sa.String(32), nullable=True),
        sa.Column("sign_on_mode", sa.String(64), nullable=True),
        sa.Column("okta_created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("okta_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("raw_json", sa.JSON, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                 nullable=False),
        sa.UniqueConstraint("tenant_id", "okta_app_id", name="uq_oktaapps_tenant_app"),
    )
    op.create_index("ix_oktaapps_tenant_label", "okta_apps", ["tenant_id", "label"])
    # Deferred FK from 0006 (column already exists, constraint did not).
    op.create_foreign_key(
        "fk_catalog_okta_app", "software_catalog", "okta_apps",
        ["okta_app_id"], ["id"],
    )

    op.create_table(
        "okta_groups",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", sa.String(128), nullable=False, index=True),
        sa.Column("okta_group_id", sa.Text, nullable=False),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("group_type", sa.String(64), nullable=True),
        sa.Column("okta_created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("okta_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_membership_updated", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                 nullable=False),
        sa.UniqueConstraint("tenant_id", "okta_group_id", name="uq_oktagroups_tenant_group"),
    )
    op.create_index("ix_oktagroups_tenant_name", "okta_groups", ["tenant_id", "name"])

    op.create_table(
        "okta_group_memberships",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", sa.String(128), nullable=False, index=True),
        sa.Column("group_id", postgresql.UUID(as_uuid=True),
                 sa.ForeignKey("okta_groups.id"), nullable=False),
        sa.Column("employee_id", postgresql.UUID(as_uuid=True),
                 sa.ForeignKey("employees.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                 nullable=False),
        sa.UniqueConstraint("group_id", "employee_id", name="uq_oktagm_group_emp"),
    )
    op.create_index("ix_oktagm_tenant_emp", "okta_group_memberships",
                    ["tenant_id", "employee_id"])

    op.create_table(
        "license_assignments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", sa.String(128), nullable=False, index=True),
        sa.Column("employee_id", postgresql.UUID(as_uuid=True),
                 sa.ForeignKey("employees.id"), nullable=False),
        sa.Column("vendor_id", postgresql.UUID(as_uuid=True),
                 sa.ForeignKey("vendors.id"), nullable=False),
        sa.Column("okta_app_id", postgresql.UUID(as_uuid=True),
                 sa.ForeignKey("okta_apps.id"), nullable=True),
        sa.Column("app_id_text", sa.Text, nullable=True),
        sa.Column("seats", sa.Integer, nullable=False, server_default="1"),
        sa.Column("assigned_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                 nullable=False),
        sa.Column("unassigned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                 nullable=False),
    )
    op.create_index("ix_lic_tenant_emp_vendor", "license_assignments",
                    ["tenant_id", "employee_id", "vendor_id"])
    op.create_index("ix_lic_tenant_vendor_status", "license_assignments",
                    ["tenant_id", "vendor_id", "status"])

    op.create_table(
        "usage_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", sa.String(128), nullable=False, index=True),
        sa.Column("employee_id", postgresql.UUID(as_uuid=True),
                 sa.ForeignKey("employees.id"), nullable=True),
        sa.Column("vendor_id", postgresql.UUID(as_uuid=True),
                 sa.ForeignKey("vendors.id"), nullable=True),
        sa.Column("okta_app_id", postgresql.UUID(as_uuid=True),
                 sa.ForeignKey("okta_apps.id"), nullable=True),
        sa.Column("app_id_text", sa.Text, nullable=True),
        sa.Column("event_type", sa.String(128), nullable=False),
        sa.Column("display_message", sa.Text, nullable=True),
        sa.Column("outcome_result", sa.String(32), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("okta_event_id", sa.Text, nullable=False),
        sa.Column("target_json", sa.JSON, nullable=True),
        sa.Column("raw_signal", sa.JSON, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                 nullable=False),
        sa.UniqueConstraint("tenant_id", "okta_event_id", name="uq_usage_tenant_oktaevt"),
    )
    op.create_index("ix_use_tenant_emp_time", "usage_events",
                    ["tenant_id", "employee_id", "occurred_at"])
    op.create_index("ix_use_tenant_vendor_time", "usage_events",
                    ["tenant_id", "vendor_id", "occurred_at"])
    op.create_index("ix_use_tenant_app_time", "usage_events",
                    ["tenant_id", "okta_app_id", "occurred_at"])

    op.create_table(
        "reconciliation_exceptions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", sa.String(128), nullable=False, index=True),
        sa.Column("invoice_id", postgresql.UUID(as_uuid=True),
                 sa.ForeignKey("invoices.id"), nullable=False),
        sa.Column("invoice_line_id", postgresql.UUID(as_uuid=True),
                 sa.ForeignKey("invoice_line_items.id"), nullable=True),
        sa.Column("contract_id", postgresql.UUID(as_uuid=True),
                 sa.ForeignKey("contracts.id"), nullable=False),
        sa.Column("contract_version_id", postgresql.UUID(as_uuid=True),
                 sa.ForeignKey("contract_terms_versioned.id"), nullable=False),
        sa.Column("po_id", postgresql.UUID(as_uuid=True),
                 sa.ForeignKey("purchase_orders.id"), nullable=True),
        sa.Column("rule_type", exception_rule, nullable=False),
        sa.Column("expected_value", sa.Numeric(14, 2), nullable=True),
        sa.Column("billed_value", sa.Numeric(14, 2), nullable=True),
        sa.Column("variance_amount", sa.Numeric(14, 2), nullable=True),
        sa.Column("variance_pct", sa.Numeric(9, 4), nullable=True),
        sa.Column("severity", sa.String(16), nullable=False, server_default="medium"),
        sa.Column("status", exception_status, nullable=False, server_default="open",
                 index=True),
        sa.Column("detected_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                 nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_rec_tenant_status", "reconciliation_exceptions",
                    ["tenant_id", "status"])
    op.create_index("ix_rec_tenant_invoice", "reconciliation_exceptions",
                    ["tenant_id", "invoice_id"])

    op.create_table(
        "maverick_alerts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", sa.String(128), nullable=False, index=True),
        sa.Column("transaction_id", postgresql.UUID(as_uuid=True),
                 sa.ForeignKey("card_transactions.id"), nullable=False),
        sa.Column("employee_id", postgresql.UUID(as_uuid=True),
                 sa.ForeignKey("employees.id"), nullable=True),
        sa.Column("merchant_name", sa.Text, nullable=False),
        sa.Column("jev_is_saas_score", sa.Numeric(5, 4), nullable=True),
        sa.Column("jev_review_score", sa.Numeric(5, 4), nullable=True),
        sa.Column("status", alert_status, nullable=False, server_default="open", index=True),
        sa.Column("capability_text", sa.Text, nullable=True),
        sa.Column("overlap_catalog_id", postgresql.UUID(as_uuid=True),
                 sa.ForeignKey("software_catalog.id"), nullable=True),
        sa.Column("overlap_score", sa.Numeric(5, 4), nullable=True),
        sa.Column("recommended_action", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                 nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                 nullable=False),
    )
    op.create_index("ix_mav_tenant_status", "maverick_alerts", ["tenant_id", "status"])
    op.create_index("ix_mav_tenant_emp", "maverick_alerts", ["tenant_id", "employee_id"])

    op.create_table(
        "seat_forecasts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", sa.String(128), nullable=False, index=True),
        sa.Column("vendor_id", postgresql.UUID(as_uuid=True),
                 sa.ForeignKey("vendors.id"), nullable=False),
        sa.Column("department_id", postgresql.UUID(as_uuid=True),
                 sa.ForeignKey("departments.id"), nullable=True),
        sa.Column("department", sa.String(128), nullable=True),
        sa.Column("forecast_date", sa.Date, nullable=False),
        sa.Column("current_seats", sa.Integer, nullable=False),
        sa.Column("recommended_seats", sa.Integer, nullable=False),
        sa.Column("retention_curve", sa.JSON, nullable=True),
        sa.Column("confidence", sa.Numeric(5, 4), nullable=True),
        sa.Column("shelfware_amount", sa.Numeric(14, 2), nullable=True),
        sa.Column("trueup_risk_amount", sa.Numeric(14, 2), nullable=True),
        sa.Column("savings_estimate", sa.Numeric(14, 2), nullable=True),
        sa.Column("model_version", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                 nullable=False),
        sa.UniqueConstraint(
            "tenant_id", "vendor_id", "department", "forecast_date",
            name="uq_forecast_tenant_vendor_dept_date",
        ),
    )

    op.create_table(
        "workflows",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", sa.String(128), nullable=False, index=True),
        sa.Column("workflow_type", workflow_type, nullable=False),
        sa.Column("title", sa.String(256), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("reference_type", sa.String(32), nullable=True),
        sa.Column("reference_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("assignee_user_id", postgresql.UUID(as_uuid=True),
                 sa.ForeignKey("users.id"), nullable=True),
        sa.Column("status", workflow_status, nullable=False, server_default="pending",
                 index=True),
        sa.Column("current_step", sa.Integer, nullable=False, server_default="1"),
        sa.Column("total_steps", sa.Integer, nullable=False, server_default="3"),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metadata", sa.JSON, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                 nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                 nullable=False),
    )
    op.create_index("ix_wf_tenant_status", "workflows", ["tenant_id", "status"])
    op.create_index("ix_wf_tenant_assignee", "workflows", ["tenant_id", "assignee_user_id"])
    op.create_index("ix_wf_tenant_ref", "workflows",
                    ["tenant_id", "reference_type", "reference_id"])

    op.create_table(
        "savings_ledger",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", sa.String(128), nullable=False, index=True),
        sa.Column("vendor_id", postgresql.UUID(as_uuid=True),
                 sa.ForeignKey("vendors.id"), nullable=True),
        sa.Column("source_type", sa.String(32), nullable=False),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False, server_default="USD"),
        sa.Column("kind", savings_kind, nullable=False),
        sa.Column("status", savings_status, nullable=False, server_default="potential"),
        sa.Column("verified_by_user_id", postgresql.UUID(as_uuid=True),
                 sa.ForeignKey("users.id"), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                 nullable=False),
    )
    op.create_index("ix_sav_tenant_kind_status", "savings_ledger",
                    ["tenant_id", "kind", "status"])
    op.create_index("ix_sav_tenant_vendor", "savings_ledger", ["tenant_id", "vendor_id"])

    op.create_table(
        "audit_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", sa.String(128), nullable=False, index=True),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True),
                 sa.ForeignKey("users.id"), nullable=True),
        sa.Column("correlation_id", sa.Text, nullable=False),
        sa.Column("mcp_server", sa.String(64), nullable=True),
        sa.Column("tool_name", sa.String(128), nullable=False),
        sa.Column("tool_version", sa.String(32), nullable=True),
        sa.Column("risk_class", risk_class, nullable=False, server_default="read_only"),
        sa.Column("auth_result", sa.String(32), nullable=False, server_default="allowed"),
        sa.Column("success", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("error_class", sa.String(128), nullable=True),
        sa.Column("latency_ms", sa.Integer, nullable=True),
        sa.Column("result_size", sa.Integer, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                 nullable=False),
    )
    op.create_index("ix_audit_tenant_time", "audit_events", ["tenant_id", "created_at"])
    op.create_index("ix_audit_tenant_corr", "audit_events", ["tenant_id", "correlation_id"])

    # New sync entities for Ramp/Okta pull-sync checkpoints. ALTER TYPE ...
    # ADD VALUE cannot run inside the migration transaction (env.py wraps
    # revisions in begin_transaction), hence the dedicated connection.
    _add_enum_values(
        "entity_type",
        ("ramp_users", "ramp_departments", "ramp_merchants", "ramp_vendors",
         "okta_apps", "okta_groups"),
    )


def downgrade() -> None:
    op.drop_index("ix_audit_tenant_corr", table_name="audit_events")
    op.drop_index("ix_audit_tenant_time", table_name="audit_events")
    op.drop_table("audit_events")
    op.drop_index("ix_sav_tenant_vendor", table_name="savings_ledger")
    op.drop_index("ix_sav_tenant_kind_status", table_name="savings_ledger")
    op.drop_table("savings_ledger")
    op.drop_index("ix_wf_tenant_ref", table_name="workflows")
    op.drop_index("ix_wf_tenant_assignee", table_name="workflows")
    op.drop_index("ix_wf_tenant_status", table_name="workflows")
    op.drop_table("workflows")
    op.drop_table("seat_forecasts")
    op.drop_index("ix_mav_tenant_emp", table_name="maverick_alerts")
    op.drop_index("ix_mav_tenant_status", table_name="maverick_alerts")
    op.drop_table("maverick_alerts")
    op.drop_index("ix_rec_tenant_invoice", table_name="reconciliation_exceptions")
    op.drop_index("ix_rec_tenant_status", table_name="reconciliation_exceptions")
    op.drop_table("reconciliation_exceptions")
    op.drop_index("ix_use_tenant_app_time", table_name="usage_events")
    op.drop_index("ix_use_tenant_vendor_time", table_name="usage_events")
    op.drop_index("ix_use_tenant_emp_time", table_name="usage_events")
    op.drop_table("usage_events")
    op.drop_index("ix_lic_tenant_vendor_status", table_name="license_assignments")
    op.drop_index("ix_lic_tenant_emp_vendor", table_name="license_assignments")
    op.drop_table("license_assignments")
    op.drop_index("ix_oktagm_tenant_emp", table_name="okta_group_memberships")
    op.drop_table("okta_group_memberships")
    op.drop_index("ix_oktagroups_tenant_name", table_name="okta_groups")
    op.drop_table("okta_groups")
    op.drop_constraint("fk_catalog_okta_app", "software_catalog", type_="foreignkey")
    op.drop_index("ix_oktaapps_tenant_label", table_name="okta_apps")
    op.drop_table("okta_apps")
    # NOTE: PG enum values cannot be removed; added entity_type values stay.
    op.execute("DROP TYPE IF EXISTS risk_class")
    op.execute("DROP TYPE IF EXISTS savings_status")
    op.execute("DROP TYPE IF EXISTS savings_kind")
    op.execute("DROP TYPE IF EXISTS workflow_status")
    op.execute("DROP TYPE IF EXISTS workflow_type")
    op.execute("DROP TYPE IF EXISTS alert_status")
    op.execute("DROP TYPE IF EXISTS exception_status")
    op.execute("DROP TYPE IF EXISTS exception_rule")
