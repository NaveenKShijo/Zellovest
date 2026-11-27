"""Intelligence + close-loop tables: Okta, outputs, actions (migration 0008).

Tables: ``okta_apps``, ``okta_groups``, ``okta_group_memberships``,
``license_assignments``, ``usage_events``, ``reconciliation_exceptions``,
``maverick_alerts``, ``seat_forecasts``, ``workflows``, ``savings_ledger``,
``audit_events``.

Design notes (see ``dbdiagram.dbml`` E-G):
- ``okta_apps`` is the *discovered* app inventory; ``software_catalog`` is
  the *approved* list (linked, never merged).
- Intelligence outputs are INSERT-only by convention: new detections are
  new rows; math is never UPDATEd in place.
- ``workflows.reference_id`` / ``savings_ledger.source_id`` /
  ``extraction_provenance.entity_id`` are polymorphic (type + id, no FK)
  so one action table serves invoices, alerts, renewals, and forecasts.
"""

import enum
import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Enum,
    Float,
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


class ExceptionRule(str, enum.Enum):
    """Reconciliation rule that fired."""

    PRICE = "price"
    QUANTITY = "quantity"
    DATE = "date"
    DISCOUNT = "discount"
    TAX = "tax"
    FREIGHT = "freight"
    PAYMENT_TERM = "payment_term"
    MISSING_PO = "missing_po"


class ExceptionStatus(str, enum.Enum):
    """Exception triage state."""

    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"
    DISMISSED = "dismissed"


class AlertStatus(str, enum.Enum):
    """Maverick-alert triage state."""

    OPEN = "open"
    NOTIFIED = "notified"
    MIGRATED = "migrated"
    DISMISSED = "dismissed"


class WorkflowType(str, enum.Enum):
    """Action workflow category."""

    INVOICE_APPROVAL = "invoice_approval"
    CONTRACT_REVIEW = "contract_review"
    VENDOR_ONBOARDING = "vendor_onboarding"
    PURCHASE_ORDER_APPROVAL = "purchase_order_approval"
    RENEWAL_NEGOTIATION = "renewal_negotiation"
    HUMAN_REVIEW = "human_review"


class WorkflowStatus(str, enum.Enum):
    """Action workflow state."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    APPROVED = "approved"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


class SavingsKind(str, enum.Enum):
    """CFO ledger split."""

    HARD_CASH = "hard_cash"
    AVOIDANCE = "avoidance"


class SavingsStatus(str, enum.Enum):
    """Ledger verification state."""

    POTENTIAL = "potential"
    VERIFIED = "verified"


class RiskClass(str, enum.Enum):
    """MCP tool risk classification."""

    READ_ONLY = "read_only"
    LOW_RISK = "low_risk"
    HIGH_RISK = "high_risk"


class OktaApp(Base):
    """Discovered Okta application (``apps.read``; raw payload kept as JSON)."""

    __tablename__ = "okta_apps"
    __table_args__ = (
        UniqueConstraint("tenant_id", "okta_app_id", name="uq_oktaapps_tenant_app"),
        Index("ix_oktaapps_tenant_label", "tenant_id", "label"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    okta_app_id: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    label: Mapped[str | None] = mapped_column(String(256), nullable=True)
    status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    sign_on_mode: Mapped[str | None] = mapped_column(String(64), nullable=True)
    okta_created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    okta_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    raw_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class OktaGroup(Base):
    """Okta group (cohort for license/churn analysis; NOT the same as departments)."""

    __tablename__ = "okta_groups"
    __table_args__ = (
        UniqueConstraint("tenant_id", "okta_group_id", name="uq_oktagroups_tenant_group"),
        Index("ix_oktagroups_tenant_name", "tenant_id", "name"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    okta_group_id: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    group_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    okta_created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    okta_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_membership_updated: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class OktaGroupMembership(Base):
    """Group-to-employee link (populated from ``GET /groups/{id}/users``)."""

    __tablename__ = "okta_group_memberships"
    __table_args__ = (
        UniqueConstraint("group_id", "employee_id", name="uq_oktagm_group_emp"),
        Index("ix_oktagm_tenant_emp", "tenant_id", "employee_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    group_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("okta_groups.id"), nullable=False
    )
    employee_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("employees.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class LicenseAssignment(Base):
    """Seat assignment of an employee to a SaaS vendor."""

    __tablename__ = "license_assignments"
    __table_args__ = (
        Index("ix_lic_tenant_emp_vendor", "tenant_id", "employee_id", "vendor_id"),
        Index("ix_lic_tenant_vendor_status", "tenant_id", "vendor_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    employee_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("employees.id"), nullable=False
    )
    vendor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("vendors.id"), nullable=False
    )
    okta_app_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("okta_apps.id"), nullable=True
    )
    app_id_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    seats: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    unassigned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ContractProductProfile(Base):
    """LLM-enriched semantic profile for one current contracted product line."""

    __tablename__ = "contract_product_profiles"
    __table_args__ = (
        UniqueConstraint("tenant_id", "contract_line_id", name="uq_contract_product_profile_line"),
        Index("ix_contract_product_profiles_tenant", "tenant_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    contract_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("contracts.id"), nullable=False
    )
    contract_line_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("contract_lines.id"), nullable=False
    )
    contract_term_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("contract_terms_versioned.id"), nullable=False
    )
    vendor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("vendors.id"), nullable=False
    )
    source_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    product_name: Mapped[str] = mapped_column(String(256), nullable=False)
    category: Mapped[str | None] = mapped_column(String(128), nullable=True)
    capabilities: Mapped[list | None] = mapped_column(JSON, nullable=True)
    use_cases: Mapped[list | None] = mapped_column(JSON, nullable=True)
    capability_text: Mapped[str] = mapped_column(Text, nullable=False)
    is_saas: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    raw_response: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class UsageEvent(Base):
    """Okta log signal (``logs.read``; ``occurred_at`` = published)."""

    __tablename__ = "usage_events"
    __table_args__ = (
        UniqueConstraint("tenant_id", "okta_event_id", name="uq_usage_tenant_oktaevt"),
        Index("ix_use_tenant_emp_time", "tenant_id", "employee_id", "occurred_at"),
        Index("ix_use_tenant_vendor_time", "tenant_id", "vendor_id", "occurred_at"),
        Index("ix_use_tenant_app_time", "tenant_id", "okta_app_id", "occurred_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    employee_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("employees.id"), nullable=True
    )
    vendor_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("vendors.id"), nullable=True
    )
    okta_app_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("okta_apps.id"), nullable=True
    )
    app_id_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    event_type: Mapped[str] = mapped_column(String(128), nullable=False)
    display_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    outcome_result: Mapped[str | None] = mapped_column(String(32), nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    okta_event_id: Mapped[str] = mapped_column(Text, nullable=False)
    target_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    raw_signal: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ReconciliationException(Base):
    """Immutable discrepancy record (deterministic AP-audit output)."""

    __tablename__ = "reconciliation_exceptions"
    __table_args__ = (
        Index("ix_rec_tenant_status", "tenant_id", "status"),
        Index("ix_rec_tenant_invoice", "tenant_id", "invoice_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    invoice_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("invoices.id"), nullable=False
    )
    invoice_line_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("invoice_line_items.id"), nullable=True
    )
    contract_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("contracts.id"), nullable=False
    )
    contract_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("contract_versions.id"), nullable=False
    )
    contract_term_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("contract_terms_versioned.id"), nullable=False
    )
    po_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("purchase_orders.id"), nullable=True
    )
    rule_type: Mapped[ExceptionRule] = mapped_column(
        Enum(
            ExceptionRule,
            name="exception_rule",
            values_callable=lambda x: [e.value for e in x],
        ),
        nullable=False,
    )
    expected_value: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    billed_value: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    variance_amount: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    variance_pct: Mapped[float | None] = mapped_column(Numeric(9, 4), nullable=True)
    severity: Mapped[str] = mapped_column(String(16), nullable=False, default="medium")
    status: Mapped[ExceptionStatus] = mapped_column(
        Enum(
            ExceptionStatus,
            name="exception_status",
            values_callable=lambda x: [e.value for e in x],
        ),
        nullable=False,
        default=ExceptionStatus.OPEN,
        index=True,
    )
    detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class MaverickAlert(Base):
    """Flagged unmanaged SaaS subscription (Jev 5-stage pipeline output)."""

    __tablename__ = "maverick_alerts"
    __table_args__ = (
        Index("ix_mav_tenant_status", "tenant_id", "status"),
        Index("ix_mav_tenant_emp", "tenant_id", "employee_id"),
        Index("ix_mav_tenant_txn", "tenant_id", "transaction_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    transaction_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("card_transactions.id"), nullable=False
    )
    employee_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("employees.id"), nullable=True
    )
    merchant_name: Mapped[str] = mapped_column(Text, nullable=False)
    jev_is_saas_score: Mapped[float | None] = mapped_column(Numeric(5, 4), nullable=True)
    jev_review_score: Mapped[float | None] = mapped_column(Numeric(5, 4), nullable=True)
    status: Mapped[AlertStatus] = mapped_column(
        Enum(AlertStatus, name="alert_status", values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        default=AlertStatus.OPEN,
        index=True,
    )
    capability_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    overlap_catalog_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("software_catalog.id"), nullable=True
    )
    overlap_contract_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("contracts.id"), nullable=True
    )
    overlap_contract_term_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("contract_terms_versioned.id"), nullable=True
    )
    overlap_score: Mapped[float | None] = mapped_column(Numeric(5, 4), nullable=True)
    recommended_action: Mapped[str | None] = mapped_column(Text, nullable=True)
    decision_evidence: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    assessment_outcome: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class SeatForecast(Base):
    """ML seat-commitment forecast per vendor+department+horizon (optimizer output)."""

    __tablename__ = "seat_forecasts"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "vendor_id",
            "department",
            "forecast_date",
            "horizon_days",
            name="uq_forecast_tenant_vendor_dept_date_horizon",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    vendor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("vendors.id"), nullable=False
    )
    department_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("departments.id"), nullable=True
    )
    department: Mapped[str | None] = mapped_column(String(128), nullable=True)
    forecast_date: Mapped[date] = mapped_column(Date, nullable=False)
    horizon_days: Mapped[int] = mapped_column(
        Integer, nullable=False, default=90, server_default="90"
    )
    renewal_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    current_seats: Mapped[int] = mapped_column(Integer, nullable=False)
    recommended_seats: Mapped[int] = mapped_column(Integer, nullable=False)
    headcount_growth_seats: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    retention_curve: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Numeric(5, 4), nullable=True)
    shelfware_amount: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    trueup_risk_amount: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    savings_estimate: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    model_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class MLModelMetric(Base):
    """Delayed ground-truth ML and financial-regret evaluation metrics."""

    __tablename__ = "ml_model_metrics"
    __table_args__ = (
        Index("ix_ml_metrics_tenant_time", "tenant_id", "evaluated_at"),
        Index("ix_ml_metrics_version_seg", "tenant_id", "model_version", "segment_type"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    model_version: Mapped[str] = mapped_column(String(64), nullable=False)
    horizon_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    segment_type: Mapped[str] = mapped_column(String(32), nullable=False, default="overall")
    segment_value: Mapped[str] = mapped_column(String(128), nullable=False, default="all")
    evaluated_seats: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cohort_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    roc_auc: Mapped[float | None] = mapped_column(Float, nullable=True)
    log_loss: Mapped[float | None] = mapped_column(Float, nullable=True)
    brier_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    ece: Mapped[float | None] = mapped_column(Float, nullable=True)
    f1: Mapped[float | None] = mapped_column(Float, nullable=True)
    realized_cost: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    naive_baseline_cost: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    oracle_cost: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    realized_savings_vs_naive: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    financial_regret: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    trueup_incident_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    evaluation_window_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    evaluation_window_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    evaluated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class MLDriftReport(Base):
    """Scheduled data-drift, score-drift, and continuous-training trigger log."""

    __tablename__ = "ml_drift_reports"
    __table_args__ = (
        Index("ix_ml_drift_tenant_time", "tenant_id", "created_at"),
        Index("ix_ml_drift_tenant_sev", "tenant_id", "severity"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    model_version: Mapped[str] = mapped_column(String(64), nullable=False)
    baseline_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reference_date: Mapped[date] = mapped_column(Date, nullable=False)
    sample_size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_psi: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    score_psi: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    max_sentinel_delta: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    severity: Mapped[str] = mapped_column(String(16), nullable=False, default="healthy")
    drifted_features: Mapped[list | None] = mapped_column(JSON, nullable=True)
    feature_metrics: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    retrain_recommended: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    retrain_triggered: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    trigger_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    training_job_uri: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Workflow(Base):
    """Human action/approval task (polymorphic target via type + id)."""

    __tablename__ = "workflows"
    __table_args__ = (
        Index("ix_wf_tenant_status", "tenant_id", "status"),
        Index("ix_wf_tenant_assignee", "tenant_id", "assignee_user_id"),
        Index("ix_wf_tenant_ref", "tenant_id", "reference_type", "reference_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    workflow_type: Mapped[WorkflowType] = mapped_column(
        Enum(
            WorkflowType,
            name="workflow_type",
            values_callable=lambda x: [e.value for e in x],
        ),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    reference_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    reference_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    assignee_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    status: Mapped[WorkflowStatus] = mapped_column(
        Enum(
            WorkflowStatus,
            name="workflow_status",
            values_callable=lambda x: [e.value for e in x],
        ),
        nullable=False,
        default=WorkflowStatus.PENDING,
        index=True,
    )
    current_step: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    total_steps: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    extra: Mapped[dict | None] = mapped_column("metadata", JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class SavingsLedgerEntry(Base):
    """CFO savings ledger (hard cash vs cost avoidance, finance-verified)."""

    __tablename__ = "savings_ledger"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "source_type",
            "source_id",
            name="uq_savings_ledger_source",
        ),
        Index("ix_sav_tenant_kind_status", "tenant_id", "kind", "status"),
        Index("ix_sav_tenant_vendor", "tenant_id", "vendor_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    vendor_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("vendors.id"), nullable=True
    )
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    amount: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="USD")
    kind: Mapped[SavingsKind] = mapped_column(
        Enum(SavingsKind, name="savings_kind", values_callable=lambda x: [e.value for e in x]),
        nullable=False,
    )
    status: Mapped[SavingsStatus] = mapped_column(
        Enum(
            SavingsStatus,
            name="savings_status",
            values_callable=lambda x: [e.value for e in x],
        ),
        nullable=False,
        default=SavingsStatus.POTENTIAL,
    )
    verified_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class AuditEvent(Base):
    """Append-only MCP/tool audit trail (PRD 25.9)."""

    __tablename__ = "audit_events"
    __table_args__ = (
        Index("ix_audit_tenant_time", "tenant_id", "created_at"),
        Index("ix_audit_tenant_corr", "tenant_id", "correlation_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    correlation_id: Mapped[str] = mapped_column(Text, nullable=False)
    mcp_server: Mapped[str | None] = mapped_column(String(64), nullable=True)
    tool_name: Mapped[str] = mapped_column(String(128), nullable=False)
    tool_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    risk_class: Mapped[RiskClass] = mapped_column(
        Enum(RiskClass, name="risk_class", values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        default=RiskClass.READ_ONLY,
    )
    auth_result: Mapped[str] = mapped_column(String(32), nullable=False, default="allowed")
    success: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    error_class: Mapped[str | None] = mapped_column(String(128), nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    result_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class DecisionPacket(Base):
    """Pre-computed, evidence-backed decision packet surfaced directly in-app."""

    __tablename__ = "decision_packets"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "packet_type",
            "entity_id",
            name="uq_decision_packet_tenant_type_entity",
        ),
        Index("ix_dp_tenant_status", "tenant_id", "status"),
        Index("ix_dp_tenant_type", "tenant_id", "packet_type"),
        Index("ix_dp_tenant_urgency", "tenant_id", "urgency_date"),
        Index("ix_dp_tenant_vendor", "tenant_id", "vendor_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    packet_type: Mapped[str] = mapped_column(String(32), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(32), nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    vendor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    recommended_action: Mapped[str | None] = mapped_column(Text, nullable=True)
    financial_impact: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="USD")
    urgency_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    source_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="pending_review", server_default="pending_review"
    )
    actioned_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    actioned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
