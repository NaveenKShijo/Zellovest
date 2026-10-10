"""Transact tables: documents + commercial truth + money (V2 DB-per-tenant ready).

Revision ID: 0007_transact
Revises: 0006_foundation

Creates (see ``dbdiagram.dbml`` C–D + ``shared/.../db/transact.py``):
documents, extraction_provenance, contracts, contract_terms_versioned,
purchase_orders, po_line_items, invoices, invoice_line_items,
card_transactions.

Notes:
- New PG enums are created idempotently (``DO ... EXCEPTION WHEN
  duplicate_object``), following 0001_initial.
- ``contract_terms_versioned`` gets ``no_overlap_contract_terms``
  ``EXCLUDE USING gist`` (requires ``btree_gist``): overlapping effective
  ranges for one contract are rejected at the database level.
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0007_transact"
down_revision = "0006_foundation"
branch_labels = None
depends_on = None


def _create_enum(type_name: str, values: tuple[str, ...]) -> None:
    labels = ", ".join(f"'{v}'" for v in values)
    op.execute(
        f"DO $$ BEGIN CREATE TYPE {type_name} AS ENUM ({labels}); "
        "EXCEPTION WHEN duplicate_object THEN NULL; END $$;"
    )


def upgrade() -> None:
    op.execute('CREATE EXTENSION IF NOT EXISTS "btree_gist"')
    _create_enum(
        "doc_type",
        ("contract", "amendment", "invoice", "purchase_order", "policy", "other"),
    )
    _create_enum(
        "doc_status", ("staged", "processing", "extracted", "review_needed", "failed")
    )
    _create_enum(
        "contract_status", ("draft", "active", "expired", "terminated", "renewed")
    )
    _create_enum(
        "po_status", ("draft", "sent", "partially_received", "received", "cancelled")
    )
    _create_enum(
        "invoice_status", ("pending", "approved", "paid", "rejected", "flagged")
    )
    _create_enum("txn_source", ("ramp", "webhook", "manual"))

    doc_type = postgresql.ENUM(
        "contract", "amendment", "invoice", "purchase_order", "policy", "other",
        name="doc_type", create_type=False,
    )
    doc_status = postgresql.ENUM(
        "staged", "processing", "extracted", "review_needed", "failed",
        name="doc_status", create_type=False,
    )
    contract_status = postgresql.ENUM(
        "draft", "active", "expired", "terminated", "renewed",
        name="contract_status", create_type=False,
    )
    po_status = postgresql.ENUM(
        "draft", "sent", "partially_received", "received", "cancelled",
        name="po_status", create_type=False,
    )
    invoice_status = postgresql.ENUM(
        "pending", "approved", "paid", "rejected", "flagged",
        name="invoice_status", create_type=False,
    )
    txn_source = postgresql.ENUM(
        "ramp", "webhook", "manual", name="txn_source", create_type=False
    )

    op.create_table(
        "documents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", sa.String(128), nullable=False, index=True),
        sa.Column("vendor_id", postgresql.UUID(as_uuid=True),
                 sa.ForeignKey("vendors.id"), nullable=True),
        sa.Column("upload_id", postgresql.UUID(as_uuid=True),
                 sa.ForeignKey("uploads.id"), nullable=True),
        sa.Column("s3_key", sa.Text, nullable=False, unique=True),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("document_type", doc_type, nullable=False),
        sa.Column("mime_type", sa.String(128), nullable=False),
        sa.Column("status", doc_status, nullable=False, server_default="staged"),
        sa.Column("classifier_confidence", sa.Numeric(5, 4), nullable=True),
        sa.Column("page_count", sa.Integer, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                 nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                 nullable=False),
        sa.UniqueConstraint("s3_key", name="uq_documents_s3_key"),
    )
    op.create_index("ix_docs_tenant_vendor_type", "documents",
                    ["tenant_id", "vendor_id", "document_type"])

    op.create_table(
        "extraction_provenance",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", sa.String(128), nullable=False, index=True),
        sa.Column("document_id", postgresql.UUID(as_uuid=True),
                 sa.ForeignKey("documents.id"), nullable=False),
        sa.Column("entity_type", sa.String(32), nullable=False),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("field_name", sa.String(128), nullable=False),
        sa.Column("field_value_text", sa.Text, nullable=False),
        sa.Column("confidence", sa.Numeric(5, 4), nullable=True),
        sa.Column("page", sa.Integer, nullable=True),
        sa.Column("bbox_json", sa.JSON, nullable=True),
        sa.Column("extraction_method", sa.String(64), nullable=True),
        sa.Column("extracted_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                 nullable=False),
    )
    op.create_index("ix_prov_tenant_doc", "extraction_provenance", ["tenant_id", "document_id"])
    op.create_index("ix_prov_tenant_entity", "extraction_provenance",
                    ["tenant_id", "entity_type", "entity_id"])

    op.create_table(
        "contracts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", sa.String(128), nullable=False, index=True),
        sa.Column("vendor_id", postgresql.UUID(as_uuid=True),
                 sa.ForeignKey("vendors.id"), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True),
                 sa.ForeignKey("documents.id"), nullable=True),
        sa.Column("contract_number", sa.String(128), nullable=False),
        sa.Column("title", sa.String(256), nullable=True),
        sa.Column("status", contract_status, nullable=False, server_default="active"),
        sa.Column("start_date", sa.Date, nullable=False),
        sa.Column("end_date", sa.Date, nullable=True),
        sa.Column("renewal_date", sa.Date, nullable=True),
        sa.Column("notice_period_days", sa.Integer, nullable=True),
        sa.Column("auto_renew", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("termination_clause", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                 nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                 nullable=False),
        sa.UniqueConstraint("tenant_id", "contract_number",
                            name="uq_contracts_tenant_number"),
    )
    op.create_index("ix_contracts_tenant_renewal", "contracts", ["tenant_id", "renewal_date"])
    op.create_index("ix_contracts_tenant_vendor", "contracts", ["tenant_id", "vendor_id"])

    op.create_table(
        "contract_terms_versioned",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", sa.String(128), nullable=False, index=True),
        sa.Column("contract_id", postgresql.UUID(as_uuid=True),
                 sa.ForeignKey("contracts.id"), nullable=False),
        sa.Column("version_no", sa.Integer, nullable=False),
        sa.Column("product_code", sa.String(128), nullable=True),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("unit_price", sa.Numeric(14, 2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False, server_default="USD"),
        sa.Column("uom", sa.String(32), nullable=True),
        sa.Column("qty_min", sa.Numeric(14, 2), nullable=True),
        sa.Column("qty_max", sa.Numeric(14, 2), nullable=True),
        sa.Column("discount_pct", sa.Numeric(7, 4), nullable=True),
        sa.Column("tax_rule", sa.Text, nullable=True),
        sa.Column("payment_terms", sa.Text, nullable=True),
        sa.Column("freight_terms", sa.Text, nullable=True),
        sa.Column("escalation_pct", sa.Numeric(7, 4), nullable=True),
        sa.Column("effective_from", sa.Date, nullable=False),
        sa.Column("effective_to", sa.Date, nullable=True),
        sa.Column("amendment_document_id", postgresql.UUID(as_uuid=True),
                 sa.ForeignKey("documents.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                 nullable=False),
        sa.UniqueConstraint("tenant_id", "contract_id", "version_no",
                            name="uq_terms_tenant_contract_ver"),
    )
    op.create_index("ix_ctv_tenant_contract_dates", "contract_terms_versioned",
                    ["tenant_id", "contract_id", "effective_from", "effective_to"])
    # NULL effective_to = current version (open-ended range to infinity).
    op.execute(
        "ALTER TABLE contract_terms_versioned ADD CONSTRAINT no_overlap_contract_terms "
        "EXCLUDE USING gist (contract_id WITH =, "
        "daterange(effective_from, COALESCE(effective_to, 'infinity'::date)) WITH &&)"
    )

    op.create_table(
        "purchase_orders",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", sa.String(128), nullable=False, index=True),
        sa.Column("vendor_id", postgresql.UUID(as_uuid=True),
                 sa.ForeignKey("vendors.id"), nullable=False),
        sa.Column("contract_id", postgresql.UUID(as_uuid=True),
                 sa.ForeignKey("contracts.id"), nullable=True),
        sa.Column("source_document_id", postgresql.UUID(as_uuid=True),
                 sa.ForeignKey("documents.id"), nullable=True),
        sa.Column("po_number", sa.String(128), nullable=False),
        sa.Column("order_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expected_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("currency", sa.String(3), nullable=False, server_default="USD"),
        sa.Column("subtotal", sa.Numeric(14, 2), nullable=False),
        sa.Column("tax_amount", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("total_amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("status", po_status, nullable=False, server_default="draft"),
        sa.Column("metadata", sa.JSON, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                 nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                 nullable=False),
        sa.UniqueConstraint("tenant_id", "po_number", name="uq_pos_tenant_number"),
    )
    op.create_index("ix_po_tenant_vendor", "purchase_orders", ["tenant_id", "vendor_id"])

    op.create_table(
        "po_line_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", sa.String(128), nullable=False, index=True),
        sa.Column("po_id", postgresql.UUID(as_uuid=True),
                 sa.ForeignKey("purchase_orders.id"), nullable=False),
        sa.Column("line_no", sa.Integer, nullable=False),
        sa.Column("description", sa.Text, nullable=False),
        sa.Column("product_code", sa.String(128), nullable=True),
        sa.Column("quantity", sa.Numeric(14, 2), nullable=False),
        sa.Column("unit_price", sa.Numeric(14, 2), nullable=False),
        sa.Column("total", sa.Numeric(14, 2), nullable=False),
        sa.UniqueConstraint("po_id", "line_no", name="uq_polines_po_lineno"),
    )

    op.create_table(
        "invoices",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", sa.String(128), nullable=False, index=True),
        sa.Column("vendor_id", postgresql.UUID(as_uuid=True),
                 sa.ForeignKey("vendors.id"), nullable=False),
        sa.Column("contract_id", postgresql.UUID(as_uuid=True),
                 sa.ForeignKey("contracts.id"), nullable=True),
        sa.Column("po_id", postgresql.UUID(as_uuid=True),
                 sa.ForeignKey("purchase_orders.id"), nullable=True),
        sa.Column("document_id", postgresql.UUID(as_uuid=True),
                 sa.ForeignKey("documents.id"), nullable=True),
        sa.Column("business_entity_id", postgresql.UUID(as_uuid=True),
                 sa.ForeignKey("business_entities.id"), nullable=True),
        sa.Column("invoice_number", sa.String(128), nullable=False),
        sa.Column("invoice_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("due_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("paid_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("currency", sa.String(3), nullable=False, server_default="USD"),
        sa.Column("subtotal", sa.Numeric(14, 2), nullable=False),
        sa.Column("tax_amount", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("total_amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("status", invoice_status, nullable=False, server_default="pending"),
        sa.Column("ramp_bill_id", sa.Text, nullable=True),
        sa.Column("invoice_url", sa.Text, nullable=True),
        sa.Column("payment_method", sa.String(64), nullable=True),
        sa.Column("payment_status", sa.String(64), nullable=True),
        sa.Column("approval_status", sa.String(64), nullable=True),
        sa.Column("status_summary", sa.String(128), nullable=True),
        sa.Column("sync_status", sa.String(64), nullable=True),
        sa.Column("ramp_created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metadata", sa.JSON, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                 nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                 nullable=False),
        sa.UniqueConstraint("tenant_id", "invoice_number", name="uq_inv_tenant_number"),
        sa.UniqueConstraint("tenant_id", "ramp_bill_id", name="uq_inv_tenant_ramp"),
    )
    op.create_index("ix_inv_tenant_vendor_date", "invoices",
                    ["tenant_id", "vendor_id", "invoice_date"])

    op.create_table(
        "invoice_line_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", sa.String(128), nullable=False, index=True),
        sa.Column("invoice_id", postgresql.UUID(as_uuid=True),
                 sa.ForeignKey("invoices.id"), nullable=False),
        sa.Column("line_no", sa.Integer, nullable=False),
        sa.Column("description", sa.Text, nullable=False),
        sa.Column("product_code", sa.String(128), nullable=True),
        sa.Column("quantity", sa.Numeric(14, 2), nullable=False),
        sa.Column("unit_price", sa.Numeric(14, 2), nullable=False),
        sa.Column("total", sa.Numeric(14, 2), nullable=False),
        sa.Column("ramp_line_id", sa.Text, nullable=True),
        sa.Column("category_id", sa.Integer, nullable=True),
        sa.Column("accounting_selections", sa.JSON, nullable=True),
        sa.Column("quantity_derived", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                 nullable=False),
        sa.UniqueConstraint("invoice_id", "line_no", name="uq_invl_invoice_lineno"),
    )
    op.create_index("ix_invl_tenant_ramp", "invoice_line_items", ["tenant_id", "ramp_line_id"])

    op.create_table(
        "card_transactions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", sa.String(128), nullable=False, index=True),
        sa.Column("employee_id", postgresql.UUID(as_uuid=True),
                 sa.ForeignKey("employees.id"), nullable=True),
        sa.Column("vendor_id", postgresql.UUID(as_uuid=True),
                 sa.ForeignKey("vendors.id"), nullable=True),
        sa.Column("merchant_id", postgresql.UUID(as_uuid=True),
                 sa.ForeignKey("merchants.id"), nullable=True),
        sa.Column("card_id", postgresql.UUID(as_uuid=True),
                 sa.ForeignKey("ramp_cards.id"), nullable=True),
        sa.Column("department_id", postgresql.UUID(as_uuid=True),
                 sa.ForeignKey("departments.id"), nullable=True),
        sa.Column("location_id", postgresql.UUID(as_uuid=True),
                 sa.ForeignKey("locations.id"), nullable=True),
        sa.Column("business_entity_id", postgresql.UUID(as_uuid=True),
                 sa.ForeignKey("business_entities.id"), nullable=True),
        sa.Column("merchant_name", sa.Text, nullable=False),
        sa.Column("merchant_domain", sa.String(256), nullable=True),
        sa.Column("amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False, server_default="USD"),
        sa.Column("txn_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cleared_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("state", sa.String(32), nullable=True),
        sa.Column("sk_category_id", sa.Integer, nullable=True),
        sa.Column("sk_category_name", sa.String(128), nullable=True),
        sa.Column("mcc", sa.String(8), nullable=True),
        sa.Column("card_last4", sa.String(8), nullable=True),
        sa.Column("cardholder_name_raw", sa.Text, nullable=True),
        sa.Column("memo", sa.Text, nullable=True),
        sa.Column("receipts", sa.JSON, nullable=True),
        sa.Column("accounting_selections", sa.JSON, nullable=True),
        sa.Column("has_been_approved", sa.Boolean, nullable=True),
        sa.Column("requirements_met", sa.Boolean, nullable=True),
        sa.Column("sync_status", sa.String(64), nullable=True),
        sa.Column("is_recurring", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("recurrence_interval_days", sa.Integer, nullable=True),
        sa.Column("source", txn_source, nullable=False, server_default="ramp"),
        sa.Column("external_id", sa.Text, nullable=False),
        sa.Column("raw_s3_key", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                 nullable=False),
        sa.UniqueConstraint("tenant_id", "external_id", name="uq_cards_tenant_ext"),
    )
    op.create_index("ix_txn_tenant_date", "card_transactions", ["tenant_id", "txn_date"])
    op.create_index("ix_txn_tenant_merchid", "card_transactions", ["tenant_id", "merchant_id"])
    op.create_index("ix_txn_tenant_merch", "card_transactions", ["tenant_id", "merchant_name"])
    op.create_index("ix_txn_tenant_emp", "card_transactions", ["tenant_id", "employee_id"])
    op.create_index("ix_txn_tenant_dept", "card_transactions", ["tenant_id", "department_id"])


def downgrade() -> None:
    op.drop_index("ix_txn_tenant_dept", table_name="card_transactions")
    op.drop_index("ix_txn_tenant_emp", table_name="card_transactions")
    op.drop_index("ix_txn_tenant_merch", table_name="card_transactions")
    op.drop_index("ix_txn_tenant_merchid", table_name="card_transactions")
    op.drop_index("ix_txn_tenant_date", table_name="card_transactions")
    op.drop_table("card_transactions")
    op.drop_index("ix_invl_tenant_ramp", table_name="invoice_line_items")
    op.drop_table("invoice_line_items")
    op.drop_index("ix_inv_tenant_vendor_date", table_name="invoices")
    op.drop_table("invoices")
    op.drop_table("po_line_items")
    op.drop_index("ix_po_tenant_vendor", table_name="purchase_orders")
    op.drop_table("purchase_orders")
    op.execute("ALTER TABLE contract_terms_versioned DROP CONSTRAINT IF EXISTS "
               "no_overlap_contract_terms")
    op.drop_index("ix_ctv_tenant_contract_dates", table_name="contract_terms_versioned")
    op.drop_table("contract_terms_versioned")
    op.drop_index("ix_contracts_tenant_vendor", table_name="contracts")
    op.drop_index("ix_contracts_tenant_renewal", table_name="contracts")
    op.drop_table("contracts")
    op.drop_index("ix_prov_tenant_entity", table_name="extraction_provenance")
    op.drop_index("ix_prov_tenant_doc", table_name="extraction_provenance")
    op.drop_table("extraction_provenance")
    op.drop_index("ix_docs_tenant_vendor_type", table_name="documents")
    op.drop_table("documents")
    op.execute("DROP TYPE IF EXISTS txn_source")
    op.execute("DROP TYPE IF EXISTS invoice_status")
    op.execute("DROP TYPE IF EXISTS po_status")
    op.execute("DROP TYPE IF EXISTS contract_status")
    op.execute("DROP TYPE IF EXISTS doc_status")
    op.execute("DROP TYPE IF EXISTS doc_type")
