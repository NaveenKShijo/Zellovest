"""Transact tables: documents + commercial truth + money (migration 0007).

Tables: ``documents``, ``extraction_provenance``, ``contracts``,
``contract_terms_versioned``, ``purchase_orders``, ``po_line_items``,
``invoices``, ``invoice_line_items``, ``card_transactions``.

Design notes (see ``dbdiagram.dbml`` C-D):
- Contract truth is versioned, never overwritten: a new amendment INSERTs
  a ``contract_terms_versioned`` row. Overlap is prevented by a Postgres
  ``EXCLUDE USING gist`` constraint (see migration 0007; not expressible
  in ``dbdiagram.dbml`` or plain SQLAlchemy column defs).
- ``invoices``/``invoice_line_items`` carry Ramp ``bills.read`` fields;
  bill lines ship ``amount`` only, so ``quantity=1, unit_price=amount`` with
  ``quantity_derived=True``.
- ``card_transactions.txn_date`` is Ramp ``user_transaction_time``;
  ``merchant_id`` (raw network entity) stays alongside denormalized
  ``merchant_name`` so unmanaged spend is queryable before vendor
  resolution.
"""

import enum
import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from zellovest_shared.db.base import Base


class DocType(str, enum.Enum):
    """Document classifier output."""

    CONTRACT = "contract"
    AMENDMENT = "amendment"
    INVOICE = "invoice"
    PURCHASE_ORDER = "purchase_order"
    POLICY = "policy"
    OTHER = "other"


class DocStatus(str, enum.Enum):
    """Document processing lifecycle."""

    STAGED = "staged"
    PROCESSING = "processing"
    EXTRACTED = "extracted"
    REVIEW_NEEDED = "review_needed"
    FAILED = "failed"


class ContractStatus(str, enum.Enum):
    """Contract header lifecycle."""

    DRAFT = "draft"
    ACTIVE = "active"
    EXPIRED = "expired"
    TERMINATED = "terminated"
    RENEWED = "renewed"


class POStatus(str, enum.Enum):
    """Purchase-order lifecycle."""

    DRAFT = "draft"
    SENT = "sent"
    PARTIALLY_RECEIVED = "partially_received"
    RECEIVED = "received"
    CANCELLED = "cancelled"


class InvoiceStatus(str, enum.Enum):
    """Invoice lifecycle (``flagged`` = reconciliation exception open)."""

    PENDING = "pending"
    APPROVED = "approved"
    PAID = "paid"
    REJECTED = "rejected"
    FLAGGED = "flagged"


class TxnSource(str, enum.Enum):
    """Card-transaction origin."""

    RAMP = "ramp"
    WEBHOOK = "webhook"
    MANUAL = "manual"


class Document(Base):
    """Procurement document metadata (bytes live in S3/GCS, vectors outside)."""

    __tablename__ = "documents"
    __table_args__ = (
        UniqueConstraint("s3_key", name="uq_documents_s3_key"),
        Index("ix_docs_tenant_vendor_type", "tenant_id", "vendor_id", "document_type"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    vendor_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("vendors.id"), nullable=True
    )
    upload_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("uploads.id"), nullable=True
    )
    s3_key: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    document_type: Mapped[DocType] = mapped_column(
        Enum(DocType, name="doc_type", values_callable=lambda x: [e.value for e in x]),
        nullable=False,
    )
    mime_type: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[DocStatus] = mapped_column(
        Enum(DocStatus, name="doc_status", values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        default=DocStatus.STAGED,
    )
    classifier_confidence: Mapped[float | None] = mapped_column(Numeric(5, 4), nullable=True)
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class ExtractionProvenance(Base):
    """Per-field extraction provenance (enterprise trust/audit trail).

    Polymorphic by design: ``entity_id`` points at a contract, invoice, or
    PO row per ``entity_type`` — no database FK so one table serves all.
    """

    __tablename__ = "extraction_provenance"
    __table_args__ = (
        Index("ix_prov_tenant_doc", "tenant_id", "document_id"),
        Index("ix_prov_tenant_entity", "tenant_id", "entity_type", "entity_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id"), nullable=False
    )
    entity_type: Mapped[str] = mapped_column(String(32), nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    field_name: Mapped[str] = mapped_column(String(128), nullable=False)
    field_value_text: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float | None] = mapped_column(Numeric(5, 4), nullable=True)
    page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bbox_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    extraction_method: Mapped[str | None] = mapped_column(String(64), nullable=True)
    extracted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Contract(Base):
    """Contract header (dates drive the 120/90/60/30-day renewal scan)."""

    __tablename__ = "contracts"
    __table_args__ = (
        UniqueConstraint("tenant_id", "contract_number", name="uq_contracts_tenant_number"),
        Index("ix_contracts_tenant_renewal", "tenant_id", "renewal_date"),
        Index("ix_contracts_tenant_vendor", "tenant_id", "vendor_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    vendor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("vendors.id"), nullable=False
    )
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id"), nullable=True
    )
    contract_number: Mapped[str] = mapped_column(String(128), nullable=False)
    title: Mapped[str | None] = mapped_column(String(256), nullable=True)
    status: Mapped[ContractStatus] = mapped_column(
        Enum(
            ContractStatus,
            name="contract_status",
            values_callable=lambda x: [e.value for e in x],
        ),
        nullable=False,
        default=ContractStatus.ACTIVE,
    )
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    renewal_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    notice_period_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    auto_renew: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    termination_clause: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class ContractTermsVersion(Base):
    """Versioned commercial terms — INSERT-only; history explains past invoices.

    Overlap across versions of one contract is rejected by migration 0007's
    ``no_overlap_contract_terms`` EXCLUDE constraint (requires btree_gist).
    """

    __tablename__ = "contract_terms_versioned"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "contract_id", "version_no", name="uq_terms_tenant_contract_ver"
        ),
        Index(
            "ix_ctv_tenant_contract_dates",
            "tenant_id",
            "contract_id",
            "effective_from",
            "effective_to",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    contract_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("contracts.id"), nullable=False
    )
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    product_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    unit_price: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="USD")
    uom: Mapped[str | None] = mapped_column(String(32), nullable=True)
    qty_min: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    qty_max: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    discount_pct: Mapped[float | None] = mapped_column(Numeric(7, 4), nullable=True)
    tax_rule: Mapped[str | None] = mapped_column(Text, nullable=True)
    payment_terms: Mapped[str | None] = mapped_column(Text, nullable=True)
    freight_terms: Mapped[str | None] = mapped_column(Text, nullable=True)
    escalation_pct: Mapped[float | None] = mapped_column(Numeric(7, 4), nullable=True)
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    amendment_document_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class PurchaseOrder(Base):
    """Purchase-order header."""

    __tablename__ = "purchase_orders"
    __table_args__ = (
        UniqueConstraint("tenant_id", "po_number", name="uq_pos_tenant_number"),
        Index("ix_po_tenant_vendor", "tenant_id", "vendor_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    vendor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("vendors.id"), nullable=False
    )
    contract_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("contracts.id"), nullable=True
    )
    source_document_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id"), nullable=True
    )
    po_number: Mapped[str] = mapped_column(String(128), nullable=False)
    order_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expected_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="USD")
    subtotal: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False)
    tax_amount: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    total_amount: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False)
    status: Mapped[POStatus] = mapped_column(
        Enum(POStatus, name="po_status", values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        default=POStatus.DRAFT,
    )
    extra: Mapped[dict | None] = mapped_column("metadata", JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class POLineItem(Base):
    """Purchase-order line (3-way-match input)."""

    __tablename__ = "po_line_items"
    __table_args__ = (UniqueConstraint("po_id", "line_no", name="uq_polines_po_lineno"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    po_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("purchase_orders.id"), nullable=False
    )
    line_no: Mapped[int] = mapped_column(Integer, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    product_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    quantity: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False)
    unit_price: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False)
    total: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False)


class Invoice(Base):
    """Invoice header; Ramp ``bills.read`` maps here (``invoice_date`` = issued_at)."""

    __tablename__ = "invoices"
    __table_args__ = (
        UniqueConstraint("tenant_id", "invoice_number", name="uq_inv_tenant_number"),
        UniqueConstraint("tenant_id", "ramp_bill_id", name="uq_inv_tenant_ramp"),
        Index("ix_inv_tenant_vendor_date", "tenant_id", "vendor_id", "invoice_date"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    vendor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("vendors.id"), nullable=False
    )
    contract_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("contracts.id"), nullable=True
    )
    po_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("purchase_orders.id"), nullable=True
    )
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id"), nullable=True
    )
    business_entity_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("business_entities.id"), nullable=True
    )
    invoice_number: Mapped[str] = mapped_column(String(128), nullable=False)
    invoice_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    due_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    paid_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="USD")
    subtotal: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False)
    tax_amount: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    total_amount: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False)
    status: Mapped[InvoiceStatus] = mapped_column(
        Enum(InvoiceStatus, name="invoice_status", values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        default=InvoiceStatus.PENDING,
    )
    # --- Ramp bills.read ---
    ramp_bill_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    invoice_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    payment_method: Mapped[str | None] = mapped_column(String(64), nullable=True)
    payment_status: Mapped[str | None] = mapped_column(String(64), nullable=True)
    approval_status: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status_summary: Mapped[str | None] = mapped_column(String(128), nullable=True)
    sync_status: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ramp_created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    extra: Mapped[dict | None] = mapped_column("metadata", JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class InvoiceLineItem(Base):
    """Invoice line; Ramp bill lines carry amount only (see quantity_derived)."""

    __tablename__ = "invoice_line_items"
    __table_args__ = (
        UniqueConstraint("invoice_id", "line_no", name="uq_invl_invoice_lineno"),
        Index("ix_invl_tenant_ramp", "tenant_id", "ramp_line_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    invoice_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("invoices.id"), nullable=False
    )
    line_no: Mapped[int] = mapped_column(Integer, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    product_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    quantity: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False)
    unit_price: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False)
    total: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False)
    ramp_line_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    category_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    accounting_selections: Mapped[list | None] = mapped_column(JSON, nullable=True)
    quantity_derived: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class CardTransaction(Base):
    """Canonical card transaction; Ramp ``transactions.read`` maps here."""

    __tablename__ = "card_transactions"
    __table_args__ = (
        UniqueConstraint("tenant_id", "external_id", name="uq_cards_tenant_ext"),
        Index("ix_txn_tenant_date", "tenant_id", "txn_date"),
        Index("ix_txn_tenant_merchid", "tenant_id", "merchant_id"),
        Index("ix_txn_tenant_merch", "tenant_id", "merchant_name"),
        Index("ix_txn_tenant_emp", "tenant_id", "employee_id"),
        Index("ix_txn_tenant_dept", "tenant_id", "department_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    employee_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("employees.id"), nullable=True
    )
    vendor_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("vendors.id"), nullable=True
    )
    merchant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("merchants.id"), nullable=True
    )
    card_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ramp_cards.id"), nullable=True
    )
    department_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("departments.id"), nullable=True
    )
    location_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("locations.id"), nullable=True
    )
    business_entity_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("business_entities.id"), nullable=True
    )
    merchant_name: Mapped[str] = mapped_column(Text, nullable=False)
    merchant_domain: Mapped[str | None] = mapped_column(String(256), nullable=True)
    amount: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="USD")
    txn_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    cleared_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    state: Mapped[str | None] = mapped_column(String(32), nullable=True)
    sk_category_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sk_category_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    mcc: Mapped[str | None] = mapped_column(String(8), nullable=True)
    card_last4: Mapped[str | None] = mapped_column(String(8), nullable=True)
    cardholder_name_raw: Mapped[str | None] = mapped_column(Text, nullable=True)
    memo: Mapped[str | None] = mapped_column(Text, nullable=True)
    receipts: Mapped[list | None] = mapped_column(JSON, nullable=True)
    accounting_selections: Mapped[list | None] = mapped_column(JSON, nullable=True)
    has_been_approved: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    requirements_met: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    sync_status: Mapped[str | None] = mapped_column(String(64), nullable=True)
    is_recurring: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    recurrence_interval_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source: Mapped[TxnSource] = mapped_column(
        Enum(TxnSource, name="txn_source", values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        default=TxnSource.RAMP,
    )
    external_id: Mapped[str] = mapped_column(Text, nullable=False)
    raw_s3_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
