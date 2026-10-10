"""Foundation tables: identity + dimensions (migration 0006).

Tables: ``tenants``, ``departments``, ``locations``, ``business_entities``,
``merchants``, ``vendors``, ``employees``, ``ramp_cards``,
``software_catalog``.

Design notes (see ``PRD.md`` 28.1/28.2 and ``dbdiagram.dbml``):
- Every table leads with ``tenant_id`` (indexed, NOT NULL). No physical FK
  to ``tenants`` by design — tenant is a deployment-level guarantee, and a
  web of 30 FKs to one parent adds insert-ordering pain for zero integrity
  gain in a single-tenant DB.
- Ramp/Okta external IDs are nullable (manual CRUD rows have none) with
  ``UNIQUE(tenant_id, ext_id)`` so sync dedupe works while NULLs stay
  distinct under Postgres semantics.
- ``departments.head_employee_id`` is intentionally a plain UUID with NO
  database FK: it would create a create-order cycle with
  ``employees.department_id``. The application resolves it; see docstring.
- ``software_catalog.okta_app_id`` arrives in migration 0008 with the
  ``okta_apps`` table (column added there, not here).
"""

import uuid
from datetime import date, datetime  # noqa: F401  (re-exported for model modules)

from sqlalchemy import (
    BigInteger,  # noqa: F401
    Boolean,
    Date,  # noqa: F401
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,  # noqa: F401
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from zellovest_shared.db.base import Base


class Tenant(Base):
    """Deployment instance record (one row per single-tenant DB in V1/V2)."""

    __tablename__ = "tenants"

    tenant_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    kms_key_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    org_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class Department(Base):
    """HR department dimension (Ramp ``departments.read``; manual rows allowed)."""

    __tablename__ = "departments"
    __table_args__ = (
        UniqueConstraint("tenant_id", "ramp_department_id", name="uq_departments_tenant_ramp"),
        Index("ix_dept_tenant_name", "tenant_id", "name"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    ramp_department_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    # Logical ref to employees.id — NO database FK (create-order cycle with
    # employees.department_id). Resolve in application code.
    head_employee_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    ramp_created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class Location(Base):
    """Work-location dimension (Ramp ``location_id``; no object spec yet)."""

    __tablename__ = "locations"
    __table_args__ = (
        UniqueConstraint("tenant_id", "ramp_location_id", name="uq_locations_tenant_ramp"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    ramp_location_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class BusinessEntity(Base):
    """Ramp business entity (``entity_id`` on bills/txns/users)."""

    __tablename__ = "business_entities"
    __table_args__ = (
        UniqueConstraint("tenant_id", "ramp_entity_id", name="uq_bizent_tenant_ramp"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    ramp_entity_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Merchant(Base):
    """Raw card-network merchant (Ramp ``merchants.read``; distinct from vendor)."""

    __tablename__ = "merchants"
    __table_args__ = (
        UniqueConstraint("tenant_id", "ramp_merchant_id", name="uq_merchants_tenant_ramp"),
        Index("ix_merch_tenant_name", "tenant_id", "name"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    ramp_merchant_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    merchant_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    icon_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    sk_category_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class Vendor(Base):
    """Unified vendor identity — every spend record resolves here (Vendor 360)."""

    __tablename__ = "vendors"
    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_vendors_tenant_name"),
        UniqueConstraint("tenant_id", "ramp_vendor_id", name="uq_vendors_tenant_ramp"),
        Index("ix_vendors_tenant_cat", "tenant_id", "category"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    domain: Mapped[str | None] = mapped_column(String(256), nullable=True)
    category: Mapped[str | None] = mapped_column(String(128), nullable=True)
    payment_terms: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    # --- Ramp vendors.read ---
    ramp_vendor_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    external_vendor_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    merchant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("merchants.id"), nullable=True
    )
    owner_employee_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("employees.id"), nullable=True
    )
    sk_category_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    accounting_remote_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    ramp_created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    ramp_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    extra: Mapped[dict | None] = mapped_column("metadata", JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class Employee(Base):
    """Company staff — cardholders (Ramp) and app users (Okta). Distinct from auth ``users``."""

    __tablename__ = "employees"
    __table_args__ = (
        UniqueConstraint("tenant_id", "email", name="uq_emp_tenant_email"),
        UniqueConstraint("tenant_id", "ramp_user_id", name="uq_emp_tenant_ramp"),
        UniqueConstraint("tenant_id", "okta_user_id", name="uq_emp_tenant_okta"),
        Index("ix_emp_tenant_dept", "tenant_id", "department_id"),
        Index("ix_emp_tenant_code", "tenant_id", "employee_code"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    email: Mapped[str] = mapped_column(String(256), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    first_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    last_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    employee_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    department_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("departments.id"), nullable=True
    )
    department_raw: Mapped[str | None] = mapped_column(String(128), nullable=True)
    location_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("locations.id"), nullable=True
    )
    business_entity_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("business_entities.id"), nullable=True
    )
    manager_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("employees.id"), nullable=True
    )
    employment_status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    ramp_user_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    ramp_role: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ramp_status: Mapped[str | None] = mapped_column(String(64), nullable=True)
    okta_user_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    okta_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ramp_created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    okta_created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    okta_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class RampCard(Base):
    """Physical corporate card (Ramp ``card_id``; holder resolves to employees)."""

    __tablename__ = "ramp_cards"
    __table_args__ = (
        UniqueConstraint("tenant_id", "ramp_card_id", name="uq_rampcards_tenant_ramp"),
        Index("ix_cards_tenant_emp", "tenant_id", "employee_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    ramp_card_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    employee_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("employees.id"), nullable=True
    )
    card_last4: Mapped[str | None] = mapped_column(String(8), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class SoftwareCatalog(Base):
    """Approved enterprise tools (overlap target for maverick-spend matching)."""

    __tablename__ = "software_catalog"
    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_catalog_tenant_name"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    vendor_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("vendors.id"), nullable=True
    )
    # FK to okta_apps.id is added in migration 0008 (table does not exist yet).
    okta_app_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    category: Mapped[str | None] = mapped_column(String(128), nullable=True)
    capability_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    website: Mapped[str | None] = mapped_column(String(256), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
