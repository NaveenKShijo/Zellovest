"""MCP-1 Procurement Intelligence server.

Business-level structured-data tools over the procurement domain. Every query
is tenant-scoped from the authenticated request context (never from tool
arguments), every list is bounded, and all financial arithmetic uses
``decimal.Decimal``. There is intentionally no ``execute_sql`` or free-form
query tool (PRD 25.2).

Time is an explicit input to calculations so the same request always returns
the same result; ``today`` is only used when a range is optional.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Iterable
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from zellovest_shared.db.core import Department, Employee, Vendor
from zellovest_shared.db.intelligence import (
    AlertStatus,
    ContractProductProfile,
    ExceptionStatus,
    LicenseAssignment,
    MaverickAlert,
    ReconciliationException,
    SavingsLedgerEntry,
    SavingsStatus,
    SeatForecast,
    UsageEvent,
)
from zellovest_shared.db.session import async_session_context
from zellovest_shared.db.transact import (
    CardTransaction,
    Contract,
    ContractStatus,
    ContractTermsVersion,
    ContractVersion,
    Document,
    Invoice,
    InvoiceLineItem,
    POLineItem,
    PurchaseOrder,
)
from zellovest_shared.mcp_contracts import MCP_PROCUREMENT
from zellovest_shared.pricing import (
    PRICE_TOLERANCE,
    compare_unit_price,
    normalize_text,
    optional_decimal,
    severity_for_variance,
    to_decimal,
    within_quantity,
)

from zellovest_mcp.errors import invalid, not_found
from zellovest_mcp.runtime import McpServerRuntime

SERVER_NAME = MCP_PROCUREMENT
SERVER_VERSION = "1.0.0"

procurement = McpServerRuntime(
    server_name=SERVER_NAME,
    display_name="Zellovest Procurement Intelligence MCP",
    version=SERVER_VERSION,
)

_ZERO = Decimal("0")


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------


def _money(value: Any) -> float:
    """Quantize a numeric value to cents and return a JSON float."""
    return float(to_decimal(value).quantize(Decimal("0.01")))


def _ratio(value: Any) -> float | None:
    """Return a Decimal ratio as a float, preserving None."""
    if value is None:
        return None
    return float(to_decimal(value))


def _iso(value: Any) -> str | None:
    """Render dates and datetimes as ISO-8601 strings."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat() if value.tzinfo else value.isoformat()
    return value.isoformat()


def _enum(value: Any) -> str | None:
    """Render an enum member as its wire value."""
    if value is None:
        return None
    return value.value if hasattr(value, "value") else str(value)


def _uuid(value: str, label: str) -> uuid.UUID:
    """Parse a UUID argument, raising a typed validation error."""
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError, AttributeError) as exc:
        raise invalid(f"{label} must be a UUID") from exc


def _currency(values: Iterable[Any]) -> str:
    """Collapse observed currencies into one code or ``MIXED``."""
    codes = {str(value) for value in values if value}
    if not codes:
        return "USD"
    if len(codes) == 1:
        return next(iter(codes))
    return "MIXED"


def _window(
    start_date: str | None, end_date: str | None
) -> tuple[datetime | None, datetime | None]:
    """Convert optional ISO dates into inclusive UTC datetimes."""
    start = datetime.combine(date.fromisoformat(start_date), time.min, UTC) if start_date else None
    end = datetime.combine(date.fromisoformat(end_date), time.max, UTC) if end_date else None
    if start and end and start > end:
        raise invalid("start_date must be on or before end_date")
    return start, end


def _annualize(unit_price: Decimal, uom: str | None) -> Decimal:
    """Annualize a per-seat price using the contract unit of measure."""
    normalized = (uom or "").strip().lower()
    if normalized in {"month", "monthly", "mo", "per month"}:
        return unit_price * Decimal("12")
    if normalized in {"quarter", "quarterly", "qtr"}:
        return unit_price * Decimal("4")
    return unit_price


def _vendor_json(vendor: Vendor) -> dict[str, Any]:
    """Serialize the subset of a vendor that tools may expose."""
    return {
        "id": str(vendor.id),
        "name": vendor.name,
        "domain": vendor.domain,
        "category": vendor.category,
        "status": vendor.status,
        "is_active": vendor.is_active,
        "external_vendor_id": vendor.external_vendor_id,
        "payment_terms": vendor.payment_terms,
        "owner_employee_id": str(vendor.owner_employee_id) if vendor.owner_employee_id else None,
    }


def _contract_json(contract: Contract, vendor: Vendor | None) -> dict[str, Any]:
    """Serialize a contract header with its vendor name."""
    return {
        "id": str(contract.id),
        "contract_number": contract.contract_number,
        "title": contract.title,
        "status": _enum(contract.status),
        "vendor_id": str(contract.vendor_id),
        "vendor_name": vendor.name if vendor else None,
        "start_date": _iso(contract.start_date),
        "end_date": _iso(contract.end_date),
        "renewal_date": _iso(contract.renewal_date),
        "notice_period_days": contract.notice_period_days,
        "auto_renew": contract.auto_renew,
        "termination_clause": contract.termination_clause,
        "document_id": str(contract.document_id) if contract.document_id else None,
    }


def _term_json(term: ContractTermsVersion) -> dict[str, Any]:
    """Serialize one versioned commercial term."""
    return {
        "id": str(term.id),
        "contract_line_id": str(term.contract_line_id),
        "contract_version_id": str(term.contract_version_id),
        "version_no": term.version_no,
        "line_no": term.line_no,
        "product_code": term.product_code,
        "description": term.description,
        "unit_price": str(to_decimal(term.unit_price)),
        "currency": term.currency,
        "uom": term.uom,
        "qty_min": str(term.qty_min) if term.qty_min is not None else None,
        "qty_max": str(term.qty_max) if term.qty_max is not None else None,
        "discount_pct": str(term.discount_pct) if term.discount_pct is not None else None,
        "tax_rule": term.tax_rule,
        "payment_terms": term.payment_terms,
        "escalation_pct": str(term.escalation_pct) if term.escalation_pct is not None else None,
        "effective_from": _iso(term.effective_from),
        "effective_to": _iso(term.effective_to),
        "amendment_document_id": (
            str(term.amendment_document_id) if term.amendment_document_id else None
        ),
    }


def _invoice_json(invoice: Invoice, vendor: Vendor | None) -> dict[str, Any]:
    """Serialize an invoice header."""
    return {
        "id": str(invoice.id),
        "invoice_number": invoice.invoice_number,
        "vendor_id": str(invoice.vendor_id),
        "vendor_name": vendor.name if vendor else None,
        "contract_id": str(invoice.contract_id) if invoice.contract_id else None,
        "po_id": str(invoice.po_id) if invoice.po_id else None,
        "document_id": str(invoice.document_id) if invoice.document_id else None,
        "invoice_date": _iso(invoice.invoice_date),
        "due_date": _iso(invoice.due_date),
        "currency": invoice.currency,
        "subtotal": _money(invoice.subtotal),
        "tax_amount": _money(invoice.tax_amount),
        "total_amount": _money(invoice.total_amount),
        "status": _enum(invoice.status),
        "payment_status": invoice.payment_status,
        "approval_status": invoice.approval_status,
    }


def _line_json(line: InvoiceLineItem) -> dict[str, Any]:
    """Serialize an invoice line item."""
    return {
        "id": str(line.id),
        "line_no": line.line_no,
        "description": line.description,
        "product_code": line.product_code,
        "quantity": str(to_decimal(line.quantity)),
        "unit_price": str(to_decimal(line.unit_price)),
        "total": str(to_decimal(line.total)),
        "category_id": line.category_id,
        "quantity_derived": line.quantity_derived,
    }


def _po_json(
    po: PurchaseOrder, vendor: Vendor | None, contract_number: str | None
) -> dict[str, Any]:
    """Serialize a purchase order header."""
    return {
        "id": str(po.id),
        "po_number": po.po_number,
        "vendor_id": str(po.vendor_id),
        "vendor_name": vendor.name if vendor else None,
        "contract_id": str(po.contract_id) if po.contract_id else None,
        "contract_number": contract_number,
        "order_date": _iso(po.order_date),
        "expected_date": _iso(po.expected_date),
        "currency": po.currency,
        "subtotal": _money(po.subtotal),
        "tax_amount": _money(po.tax_amount),
        "total_amount": _money(po.total_amount),
        "status": _enum(po.status),
    }


def _latest_terms(rows: Iterable[ContractTermsVersion]) -> list[ContractTermsVersion]:
    """Keep the highest version for each contract line, ordered by line."""
    latest: dict[uuid.UUID, ContractTermsVersion] = {}
    for row in rows:
        current = latest.get(row.contract_line_id)
        if current is None or row.version_no > current.version_no:
            latest[row.contract_line_id] = row
    return sorted(latest.values(), key=lambda row: (row.line_no, row.version_no))


async def _find_vendor(
    session: AsyncSession,
    tenant_id: str,
    *,
    vendor_id: str | None = None,
    vendor_name: str | None = None,
    domain: str | None = None,
) -> Vendor:
    """Resolve exactly one tenant-scoped vendor from an id, name, or domain."""
    stmt = select(Vendor).where(Vendor.tenant_id == tenant_id)
    if vendor_id:
        stmt = stmt.where(Vendor.id == _uuid(vendor_id, "vendor_id"))
        vendor = await session.scalar(stmt)
        if vendor is None:
            raise not_found("vendor")
        return vendor

    if vendor_name:
        normalized = vendor_name.strip()
        exact = await session.scalar(
            stmt.where(func.lower(Vendor.name) == normalized.lower()).limit(1)
        )
        if exact is not None:
            return exact
        candidates = (
            await session.scalars(stmt.where(Vendor.name.ilike(f"%{normalized}%")).limit(2))
        ).all()
        if len(candidates) == 1:
            return candidates[0]
        if len(candidates) > 1:
            raise invalid("vendor_name is ambiguous; supply vendor_id")
        raise not_found("vendor")

    if domain:
        normalized = domain.strip().lower().removeprefix("www.")
        vendor = await session.scalar(
            stmt.where(func.lower(Vendor.domain) == normalized).limit(1)
        )
        if vendor is None:
            raise not_found("vendor")
        return vendor

    raise invalid("one of vendor_id, vendor_name, or domain is required")


async def _terms_for_contract(
    session: AsyncSession, tenant_id: str, contract_id: uuid.UUID
) -> list[ContractTermsVersion]:
    """Return the current (highest-version) terms for every contract line."""
    rows = (
        await session.scalars(
            select(ContractTermsVersion)
            .where(
                ContractTermsVersion.tenant_id == tenant_id,
                ContractTermsVersion.contract_id == contract_id,
            )
            .order_by(ContractTermsVersion.line_no, ContractTermsVersion.version_no)
        )
    ).all()
    return _latest_terms(rows)


def _annual_contract_value(terms: Iterable[ContractTermsVersion]) -> Decimal:
    """Sum line values using contracted quantity when available."""
    total = _ZERO
    for term in terms:
        quantity = optional_decimal(term.qty_max) or optional_decimal(term.qty_min) or Decimal("1")
        total += to_decimal(term.unit_price) * quantity
    return total


# ---------------------------------------------------------------------------
# Read tools
# ---------------------------------------------------------------------------


@procurement.tool("get_vendor")
async def get_vendor(context, arguments: dict[str, Any]) -> dict[str, Any]:
    """Return one vendor with bounded related-record counts."""
    async with async_session_context() as session:
        vendor = await _find_vendor(
            session,
            context.tenant_id,
            vendor_id=arguments.get("vendor_id"),
            vendor_name=arguments.get("vendor_name"),
            domain=arguments.get("domain"),
        )
        contract_count = await session.scalar(
            select(func.count(Contract.id)).where(
                Contract.tenant_id == context.tenant_id, Contract.vendor_id == vendor.id
            )
        )
        invoice_count = await session.scalar(
            select(func.count(Invoice.id)).where(
                Invoice.tenant_id == context.tenant_id, Invoice.vendor_id == vendor.id
            )
        )
        license_count = await session.scalar(
            select(func.coalesce(func.sum(LicenseAssignment.seats), 0)).where(
                LicenseAssignment.tenant_id == context.tenant_id,
                LicenseAssignment.vendor_id == vendor.id,
                LicenseAssignment.unassigned_at.is_(None),
            )
        )
        document_count = await session.scalar(
            select(func.count(Document.id)).where(
                Document.tenant_id == context.tenant_id, Document.vendor_id == vendor.id
            )
        )
        return {
            "vendor": _vendor_json(vendor),
            "counts": {
                "contracts": int(contract_count or 0),
                "invoices": int(invoice_count or 0),
                "assigned_licenses": int(license_count or 0),
                "documents": int(document_count or 0),
            },
            "as_of": datetime.now(UTC).isoformat(),
            "summary": (
                f"{vendor.name}: {contract_count or 0} contracts, "
                f"{invoice_count or 0} invoices"
            ),
        }


@procurement.tool("get_contract")
async def get_contract(context, arguments: dict[str, Any]) -> dict[str, Any]:
    """Return a contract header, current terms, and amendment lineage."""
    async with async_session_context() as session:
        stmt = (
            select(Contract, Vendor)
            .outerjoin(Vendor, Contract.vendor_id == Vendor.id)
            .where(Contract.tenant_id == context.tenant_id)
        )
        if arguments.get("contract_id"):
            stmt = stmt.where(Contract.id == _uuid(arguments["contract_id"], "contract_id"))
        elif arguments.get("contract_number"):
            stmt = stmt.where(
                func.lower(Contract.contract_number)
                == str(arguments["contract_number"]).strip().lower()
            )
        else:
            raise invalid("contract_id or contract_number is required")
        row = (await session.execute(stmt)).first()
        if row is None:
            raise not_found("contract")
        contract, vendor = row
        terms = await _terms_for_contract(session, context.tenant_id, contract.id)
        versions: list[dict[str, Any]] = []
        if arguments.get("include_versions", True):
            version_rows = (
                await session.scalars(
                    select(ContractVersion)
                    .where(
                        ContractVersion.tenant_id == context.tenant_id,
                        ContractVersion.contract_id == contract.id,
                    )
                    .order_by(ContractVersion.version_no)
                )
            ).all()
            versions = [
                {
                    "id": str(version.id),
                    "version_no": version.version_no,
                    "change_type": _enum(version.change_type),
                    "effective_from": _iso(version.effective_from),
                    "effective_to": _iso(version.effective_to),
                    "source_document_id": (
                        str(version.source_document_id) if version.source_document_id else None
                    ),
                    "parent_version_id": (
                        str(version.parent_version_id) if version.parent_version_id else None
                    ),
                }
                for version in version_rows
            ]
        return {
            "contract": {
                **_contract_json(contract, vendor),
                "current_annual_value": _money(_annual_contract_value(terms)),
            },
            "terms": [_term_json(term) for term in terms],
            "versions": versions,
            "as_of": datetime.now(UTC).isoformat(),
            "summary": (
                f"{contract.contract_number}: {len(terms)} priced lines, "
                f"{len(versions)} versions"
            ),
        }


@procurement.tool("get_invoice")
async def get_invoice(context, arguments: dict[str, Any]) -> dict[str, Any]:
    """Return one invoice with its line items and open audit exceptions."""
    async with async_session_context() as session:
        stmt = (
            select(Invoice, Vendor)
            .outerjoin(Vendor, Invoice.vendor_id == Vendor.id)
            .where(Invoice.tenant_id == context.tenant_id)
        )
        if arguments.get("invoice_id"):
            stmt = stmt.where(Invoice.id == _uuid(arguments["invoice_id"], "invoice_id"))
        elif arguments.get("invoice_number"):
            stmt = stmt.where(
                func.lower(Invoice.invoice_number)
                == str(arguments["invoice_number"]).strip().lower()
            )
        else:
            raise invalid("invoice_id or invoice_number is required")
        row = (await session.execute(stmt)).first()
        if row is None:
            raise not_found("invoice")
        invoice, vendor = row
        lines = (
            await session.scalars(
                select(InvoiceLineItem)
                .where(
                    InvoiceLineItem.tenant_id == context.tenant_id,
                    InvoiceLineItem.invoice_id == invoice.id,
                )
                .order_by(InvoiceLineItem.line_no)
            )
        ).all()
        exceptions = (
            await session.scalars(
                select(ReconciliationException)
                .where(
                    ReconciliationException.tenant_id == context.tenant_id,
                    ReconciliationException.invoice_id == invoice.id,
                )
                .order_by(ReconciliationException.detected_at.desc())
            )
        ).all()
        return {
            "invoice": _invoice_json(invoice, vendor),
            "line_items": [_line_json(line) for line in lines],
            "exceptions": [
                {
                    "id": str(exception.id),
                    "rule_type": _enum(exception.rule_type),
                    "severity": exception.severity,
                    "status": _enum(exception.status),
                    "expected_value": (
                        _money(exception.expected_value)
                        if exception.expected_value is not None
                        else None
                    ),
                    "billed_value": (
                        _money(exception.billed_value)
                        if exception.billed_value is not None
                        else None
                    ),
                    "variance_amount": (
                        _money(exception.variance_amount)
                        if exception.variance_amount is not None
                        else None
                    ),
                    "variance_pct": _ratio(exception.variance_pct),
                }
                for exception in exceptions
            ],
            "as_of": datetime.now(UTC).isoformat(),
            "summary": (
                f"{invoice.invoice_number}: {len(lines)} lines, "
                f"{len(exceptions)} exceptions"
            ),
        }


@procurement.tool("get_purchase_order")
async def get_purchase_order(context, arguments: dict[str, Any]) -> dict[str, Any]:
    """Return one purchase order with lines and its source contract."""
    async with async_session_context() as session:
        stmt = (
            select(PurchaseOrder, Vendor)
            .outerjoin(Vendor, PurchaseOrder.vendor_id == Vendor.id)
            .where(PurchaseOrder.tenant_id == context.tenant_id)
        )
        if arguments.get("po_id"):
            stmt = stmt.where(PurchaseOrder.id == _uuid(arguments["po_id"], "po_id"))
        elif arguments.get("po_number"):
            stmt = stmt.where(
                func.lower(PurchaseOrder.po_number)
                == str(arguments["po_number"]).strip().lower()
            )
        else:
            raise invalid("po_id or po_number is required")
        row = (await session.execute(stmt)).first()
        if row is None:
            raise not_found("purchase order")
        po, vendor = row
        lines = (
            await session.scalars(
                select(POLineItem)
                .where(
                    POLineItem.tenant_id == context.tenant_id,
                    POLineItem.po_id == po.id,
                )
                .order_by(POLineItem.line_no)
            )
        ).all()
        contract_number = None
        if po.contract_id:
            contract_number = await session.scalar(
                select(Contract.contract_number).where(
                    Contract.tenant_id == context.tenant_id, Contract.id == po.contract_id
                )
            )
        return {
            "purchase_order": _po_json(po, vendor, contract_number),
            "line_items": [
                {
                    "id": str(line.id),
                    "line_no": line.line_no,
                    "description": line.description,
                    "product_code": line.product_code,
                    "quantity": str(to_decimal(line.quantity)),
                    "unit_price": str(to_decimal(line.unit_price)),
                    "total": str(to_decimal(line.total)),
                }
                for line in lines
            ],
            "as_of": datetime.now(UTC).isoformat(),
            "summary": (
                f"{po.po_number}: {len(lines)} lines, "
                f"{_money(po.total_amount)} {po.currency}"
            ),
        }


@procurement.tool("get_vendor_spend")
async def get_vendor_spend(context, arguments: dict[str, Any]) -> dict[str, Any]:
    """Sum invoice and card spend for one vendor with a monthly breakdown."""
    start, end = _window(arguments.get("start_date"), arguments.get("end_date"))
    include = set(arguments.get("include") or ["invoices", "card_transactions"])
    async with async_session_context() as session:
        vendor = await _find_vendor(
            session, context.tenant_id, vendor_id=arguments["vendor_id"]
        )
        invoice_total = _ZERO
        card_total = _ZERO
        by_month: dict[str, dict[str, Decimal]] = defaultdict(
            lambda: {"invoices": _ZERO, "card_transactions": _ZERO}
        )
        currencies: list[str] = []

        if "invoices" in include:
            invoice_stmt = select(Invoice).where(
                Invoice.tenant_id == context.tenant_id, Invoice.vendor_id == vendor.id
            )
            if start:
                invoice_stmt = invoice_stmt.where(Invoice.invoice_date >= start)
            if end:
                invoice_stmt = invoice_stmt.where(Invoice.invoice_date <= end)
            for invoice in (await session.scalars(invoice_stmt)).all():
                amount = to_decimal(invoice.total_amount)
                invoice_total += amount
                currencies.append(invoice.currency)
                key = invoice.invoice_date.strftime("%Y-%m")
                by_month[key]["invoices"] += amount

        if "card_transactions" in include:
            conditions = []
            if vendor.domain:
                conditions.append(
                    func.lower(CardTransaction.merchant_domain)
                    == vendor.domain.lower().removeprefix("www.")
                )
            conditions.append(func.lower(CardTransaction.merchant_name) == vendor.name.lower())
            card_stmt = select(CardTransaction).where(
                CardTransaction.tenant_id == context.tenant_id,
                or_(CardTransaction.vendor_id == vendor.id, *conditions),
            )
            if start:
                card_stmt = card_stmt.where(CardTransaction.txn_date >= start)
            if end:
                card_stmt = card_stmt.where(CardTransaction.txn_date <= end)
            for transaction in (await session.scalars(card_stmt)).all():
                amount = to_decimal(transaction.amount)
                card_total += amount
                currencies.append(transaction.currency)
                key = transaction.txn_date.strftime("%Y-%m")
                by_month[key]["card_transactions"] += amount

        breakdown = [
            {
                "month": month,
                "invoices": _money(values["invoices"]),
                "card_transactions": _money(values["card_transactions"]),
                "total": _money(values["invoices"] + values["card_transactions"]),
            }
            for month, values in sorted(by_month.items())
        ]
        return {
            "vendor_id": str(vendor.id),
            "vendor_name": vendor.name,
            "invoice_total": _money(invoice_total),
            "card_total": _money(card_total),
            "total_spend": _money(invoice_total + card_total),
            "currency": _currency(currencies),
            "breakdown": breakdown,
            "period": {
                "start_date": arguments.get("start_date"),
                "end_date": arguments.get("end_date"),
            },
            "methodology": (
                "Sum of invoice.total_amount and card_transaction.amount in the "
                "tenant; card rows match vendor_id, vendor domain, or exact "
                "merchant name. No FX normalization is applied."
            ),
            "as_of": datetime.now(UTC).isoformat(),
            "summary": (
                f"{vendor.name}: {_money(invoice_total + card_total)} total spend "
                f"across {len(breakdown)} periods"
            ),
        }


@procurement.tool("get_license_usage")
async def get_license_usage(context, arguments: dict[str, Any]) -> dict[str, Any]:
    """Return seat counts, utilization, recoverable spend, and forecast."""
    inactive_days = int(arguments.get("inactive_days") or 30)
    cutoff = datetime.now(UTC) - timedelta(days=inactive_days)
    async with async_session_context() as session:
        vendor = await _find_vendor(
            session, context.tenant_id, vendor_id=arguments["vendor_id"]
        )
        assignments = (
            await session.scalars(
                select(LicenseAssignment).where(
                    LicenseAssignment.tenant_id == context.tenant_id,
                    LicenseAssignment.vendor_id == vendor.id,
                    LicenseAssignment.unassigned_at.is_(None),
                )
            )
        ).all()
        assigned_seats = sum(int(item.seats or 0) for item in assignments)

        active_rows = await session.execute(
            select(
                func.count(func.distinct(UsageEvent.employee_id)),
                func.max(UsageEvent.occurred_at),
            ).where(
                UsageEvent.tenant_id == context.tenant_id,
                UsageEvent.vendor_id == vendor.id,
                UsageEvent.occurred_at >= cutoff,
                UsageEvent.outcome_result.is_(None) | (UsageEvent.outcome_result == "SUCCESS"),
            )
        )
        active_seats, last_activity = active_rows.one()
        active_seats = int(active_seats or 0)

        term_rows = (
            await session.scalars(
                select(ContractTermsVersion)
                .join(Contract, Contract.id == ContractTermsVersion.contract_id)
                .where(
                    ContractTermsVersion.tenant_id == context.tenant_id,
                    Contract.vendor_id == vendor.id,
                    Contract.status == ContractStatus.ACTIVE,
                )
                .order_by(ContractTermsVersion.version_no.desc())
            )
        ).all()
        current_terms = _latest_terms(term_rows)
        purchased_seats = int(
            sum(
                int(optional_decimal(term.qty_max) or optional_decimal(term.qty_min) or 0)
                for term in current_terms
            )
        )
        annual_price = _ZERO
        for term in current_terms:
            annual_price += _annualize(to_decimal(term.unit_price), term.uom)
        if not current_terms:
            annual_price = _ZERO

        inactive_seats = max(0, assigned_seats - active_seats)
        utilization = (active_seats / assigned_seats * 100) if assigned_seats else 0.0
        recoverable = (annual_price * inactive_seats).quantize(Decimal("0.01"))

        forecast = await session.scalar(
            select(SeatForecast)
            .where(
                SeatForecast.tenant_id == context.tenant_id,
                SeatForecast.vendor_id == vendor.id,
            )
            .order_by(SeatForecast.forecast_date.desc(), SeatForecast.created_at.desc())
            .limit(1)
        )
        return {
            "vendor_id": str(vendor.id),
            "vendor_name": vendor.name,
            "purchased_seats": purchased_seats or assigned_seats,
            "assigned_seats": assigned_seats,
            "active_seats": active_seats,
            "inactive_seats": inactive_seats,
            "utilization_pct": round(utilization, 2),
            "inactive_days": inactive_days,
            "annual_unit_price": _money(annual_price),
            "recoverable_annual_spend": _money(recoverable),
            "available_seats": max(0, (purchased_seats or assigned_seats) - assigned_seats),
            "last_activity_at": _iso(last_activity),
            "forecast": (
                {
                    "forecast_date": _iso(forecast.forecast_date),
                    "current_seats": forecast.current_seats,
                    "recommended_seats": forecast.recommended_seats,
                    "confidence": _ratio(forecast.confidence),
                    "shelfware_amount": (
                        _money(forecast.shelfware_amount)
                        if forecast.shelfware_amount is not None
                        else None
                    ),
                    "trueup_risk_amount": (
                        _money(forecast.trueup_risk_amount)
                        if forecast.trueup_risk_amount is not None
                        else None
                    ),
                    "savings_estimate": (
                        _money(forecast.savings_estimate)
                        if forecast.savings_estimate is not None
                        else None
                    ),
                    "model_version": forecast.model_version,
                }
                if forecast
                else None
            ),
            "methodology": (
                "Assigned seats are active LicenseAssignment rows. Active seats "
                "are distinct employees with an Okta usage event in the window. "
                "Recoverable spend multiplies inactive seats by the annualized "
                "current contract unit price (monthly terms x12)."
            ),
            "as_of": datetime.now(UTC).isoformat(),
            "summary": (
                f"{vendor.name}: {active_seats}/{assigned_seats} seats active "
                f"({round(utilization, 1)}%)"
            ),
        }


def _urgency_badge(days_until: int) -> str:
    """Bucket a renewal countdown into the UI badge vocabulary."""
    if days_until <= 30:
        return "30d"
    if days_until <= 60:
        return "60d"
    if days_until <= 90:
        return "90d"
    if days_until <= 120:
        return "120d"
    return "future"


@procurement.tool("find_renewals")
async def find_renewals(context, arguments: dict[str, Any]) -> dict[str, Any]:
    """List upcoming renewals with notice deadlines and measured utilization."""
    days_ahead = int(arguments.get("days_ahead") or 120)
    badge = arguments.get("badge") or "all"
    today = datetime.now(UTC).date()
    max_date = today + timedelta(days=days_ahead)
    async with async_session_context() as session:
        stmt = (
            select(Contract, Vendor)
            .outerjoin(Vendor, Contract.vendor_id == Vendor.id)
            .where(
                Contract.tenant_id == context.tenant_id,
                Contract.status == ContractStatus.ACTIVE,
                or_(Contract.renewal_date.is_not(None), Contract.end_date.is_not(None)),
            )
        )
        if arguments.get("auto_renew_only"):
            stmt = stmt.where(Contract.auto_renew.is_(True))
        if arguments.get("vendor_id"):
            stmt = stmt.where(Contract.vendor_id == _uuid(arguments["vendor_id"], "vendor_id"))

        rows = (await session.execute(stmt)).all()
        renewals: list[dict[str, Any]] = []
        for contract, vendor in rows:
            renewal = contract.renewal_date or contract.end_date
            if renewal is None:
                continue
            days_until = (renewal - today).days
            if renewal > max_date or days_until < -30:
                continue
            notice_period = (
                contract.notice_period_days
                if contract.notice_period_days is not None
                else 30
            )
            notice_deadline = renewal - timedelta(days=notice_period)
            days_to_notice = (notice_deadline - today).days
            computed_badge = _urgency_badge(days_until)
            if badge != "all" and computed_badge != badge:
                continue

            terms = await _terms_for_contract(session, context.tenant_id, contract.id)
            annual_value = _annual_contract_value(terms)
            utilization = await _measured_utilization(
                session, context.tenant_id, contract.vendor_id
            )
            renewals.append(
                {
                    "contract_id": str(contract.id),
                    "contract_number": contract.contract_number,
                    "vendor_id": str(contract.vendor_id),
                    "vendor_name": vendor.name if vendor else None,
                    "annual_value": _money(annual_value),
                    "currency": _currency(term.currency for term in terms),
                    "renewal_date": renewal.isoformat(),
                    "days_until_renewal": days_until,
                    "badge": computed_badge,
                    "auto_renew": contract.auto_renew,
                    "notice_period_days": notice_period,
                    "notice_deadline_date": notice_deadline.isoformat(),
                    "days_until_notice_deadline": days_to_notice,
                    "is_notice_window_active": days_to_notice <= 0 <= days_until,
                    "utilization_pct": utilization,
                }
            )
        renewals.sort(key=lambda item: item["days_until_renewal"])
        limited = renewals[: int(arguments.get("limit") or 20)]
        return {
            "renewals": limited,
            "count": len(limited),
            "total_matching": len(renewals),
            "as_of": today.isoformat(),
            "summary": (
                f"{len(limited)} renewals within {days_ahead} days"
                if limited
                else f"no renewals within {days_ahead} days"
            ),
        }


async def _measured_utilization(
    session: AsyncSession, tenant_id: str, vendor_id: uuid.UUID
) -> float | None:
    """Return measured seat utilization for a vendor, or None without seats."""
    assigned = await session.scalar(
        select(func.coalesce(func.sum(LicenseAssignment.seats), 0)).where(
            LicenseAssignment.tenant_id == tenant_id,
            LicenseAssignment.vendor_id == vendor_id,
            LicenseAssignment.unassigned_at.is_(None),
        )
    )
    if not assigned:
        return None
    cutoff = datetime.now(UTC) - timedelta(days=30)
    active = await session.scalar(
        select(func.count(func.distinct(UsageEvent.employee_id))).where(
            UsageEvent.tenant_id == tenant_id,
            UsageEvent.vendor_id == vendor_id,
            UsageEvent.occurred_at >= cutoff,
        )
    )
    return round((int(active or 0) / int(assigned)) * 100, 2)


@procurement.tool("get_reconciliation_exception")
async def get_reconciliation_exception(context, arguments: dict[str, Any]) -> dict[str, Any]:
    """Return one immutable exception with every linked commercial artifact."""
    async with async_session_context() as session:
        exception = await session.scalar(
            select(ReconciliationException).where(
                ReconciliationException.tenant_id == context.tenant_id,
                ReconciliationException.id
                == _uuid(arguments["exception_id"], "exception_id"),
            )
        )
        if exception is None:
            raise not_found("reconciliation exception")
        invoice = await session.scalar(
            select(Invoice).where(
                Invoice.tenant_id == context.tenant_id, Invoice.id == exception.invoice_id
            )
        )
        contract = await session.scalar(
            select(Contract).where(
                Contract.tenant_id == context.tenant_id, Contract.id == exception.contract_id
            )
        )
        term = await session.scalar(
            select(ContractTermsVersion).where(
                ContractTermsVersion.tenant_id == context.tenant_id,
                ContractTermsVersion.id == exception.contract_term_id,
            )
        )
        po = None
        if exception.po_id:
            po = await session.scalar(
                select(PurchaseOrder).where(
                    PurchaseOrder.tenant_id == context.tenant_id,
                    PurchaseOrder.id == exception.po_id,
                )
            )
        vendor = None
        if invoice is not None:
            vendor = await session.scalar(
                select(Vendor).where(
                    Vendor.tenant_id == context.tenant_id, Vendor.id == invoice.vendor_id
                )
            )
        return {
            "exception": {
                "id": str(exception.id),
                "rule_type": _enum(exception.rule_type),
                "severity": exception.severity,
                "status": _enum(exception.status),
                "expected_value": (
                    _money(exception.expected_value)
                    if exception.expected_value is not None
                    else None
                ),
                "billed_value": (
                    _money(exception.billed_value)
                    if exception.billed_value is not None
                    else None
                ),
                "variance_amount": (
                    _money(exception.variance_amount)
                    if exception.variance_amount is not None
                    else None
                ),
                "variance_pct": _ratio(exception.variance_pct),
                "detected_at": _iso(exception.detected_at),
                "resolved_at": _iso(exception.resolved_at),
                "invoice_line_id": (
                    str(exception.invoice_line_id) if exception.invoice_line_id else None
                ),
                "contract_version_id": str(exception.contract_version_id),
                "contract_term_id": str(exception.contract_term_id),
                "document_id": (
                    str(invoice.document_id) if invoice and invoice.document_id else None
                ),
                "severity_rationale": severity_for_variance(_ratio(exception.variance_pct)),
            },
            "invoice": _invoice_json(invoice, vendor) if invoice else None,
            "contract": _contract_json(contract, vendor) if contract else None,
            "term": _term_json(term) if term else None,
            "purchase_order": (
                {"id": str(po.id), "po_number": po.po_number, "status": _enum(po.status)}
                if po
                else None
            ),
            "as_of": datetime.now(UTC).isoformat(),
            "summary": (
                f"{_enum(exception.rule_type)} variance "
                f"{_money(exception.variance_amount or 0)}"
            ),
        }


@procurement.tool("compare_invoice_contract")
async def compare_invoice_contract(context, arguments: dict[str, Any]) -> dict[str, Any]:
    """Deterministically compare invoice lines to the terms in force."""
    async with async_session_context() as session:
        invoice = await session.scalar(
            select(Invoice).where(
                Invoice.tenant_id == context.tenant_id,
                Invoice.id == _uuid(arguments["invoice_id"], "invoice_id"),
            )
        )
        if invoice is None:
            raise not_found("invoice")
        contract_id = arguments.get("contract_id") or (
            str(invoice.contract_id) if invoice.contract_id else None
        )
        if not contract_id:
            raise invalid("invoice has no contract; supply contract_id")
        contract = await session.scalar(
            select(Contract).where(
                Contract.tenant_id == context.tenant_id,
                Contract.id == _uuid(contract_id, "contract_id"),
            )
        )
        if contract is None:
            raise not_found("contract")

        invoice_date = invoice.invoice_date.date()
        candidates = (
            await session.scalars(
                select(ContractTermsVersion)
                .where(
                    ContractTermsVersion.tenant_id == context.tenant_id,
                    ContractTermsVersion.contract_id == contract.id,
                    ContractTermsVersion.effective_from <= invoice_date,
                )
                .order_by(ContractTermsVersion.line_no, ContractTermsVersion.version_no)
            )
        ).all()
        in_force = [
            term
            for term in candidates
            if term.effective_to is None or term.effective_to >= invoice_date
        ]
        terms = _latest_terms(in_force)
        by_code = {
            normalize_text(term.product_code): term for term in terms if term.product_code
        }
        by_description = {normalize_text(term.description): term for term in terms}

        lines = (
            await session.scalars(
                select(InvoiceLineItem)
                .where(
                    InvoiceLineItem.tenant_id == context.tenant_id,
                    InvoiceLineItem.invoice_id == invoice.id,
                )
                .order_by(InvoiceLineItem.line_no)
            )
        ).all()

        contract_version_id = str(terms[0].contract_version_id) if terms else None
        results: list[dict[str, Any]] = []
        findings: list[dict[str, Any]] = []
        expected_total = _ZERO
        billed_total = _ZERO

        for line in lines:
            quantity = to_decimal(line.quantity)
            billed_price = to_decimal(line.unit_price)
            billed_line = to_decimal(line.total)
            billed_total += billed_line
            term = by_code.get(normalize_text(line.product_code)) or by_description.get(
                normalize_text(line.description)
            )
            if term is None:
                findings.append(
                    {
                        "code": "unmatched_invoice_line",
                        "severity": "medium",
                        "line_no": line.line_no,
                        "message": "no contract term matched this invoice line",
                    }
                )
                results.append(
                    {
                        "line_no": line.line_no,
                        "description": line.description,
                        "matched": False,
                        "billed_unit_price": str(billed_price),
                        "billed_total": str(billed_line),
                        "quantity": str(quantity),
                    }
                )
                continue
            contract_price = to_decimal(term.unit_price)
            expected_line = (contract_price * quantity).quantize(Decimal("0.01"))
            expected_total += expected_line
            comparison = compare_unit_price(contract_price, billed_price)
            quantity_ok = within_quantity(term.qty_min, term.qty_max, quantity)
            total_variance = (billed_line - expected_line).quantize(Decimal("0.01"))
            line_findings: list[dict[str, Any]] = []
            if comparison["exception"]:
                line_findings.append(
                    {
                        "code": "unit_price_variance",
                        "severity": severity_for_variance(comparison["variance_pct"]),
                        "message": (
                            f"billed {billed_price} vs contract {contract_price} "
                            f"({comparison['variance_pct']}%)"
                        ),
                    }
                )
            if not quantity_ok:
                line_findings.append(
                    {
                        "code": "quantity_out_of_bounds",
                        "severity": "high",
                        "message": (
                            f"quantity {quantity} outside contracted bounds "
                            f"[{term.qty_min}, {term.qty_max}]"
                        ),
                    }
                )
            if abs(total_variance) > PRICE_TOLERANCE:
                line_findings.append(
                    {
                        "code": "line_total_variance",
                        "severity": severity_for_variance(
                            float((total_variance / expected_line) * 100)
                            if expected_line
                            else None
                        ),
                        "message": f"billed total differs by {total_variance}",
                    }
                )
            for finding in line_findings:
                findings.append({"line_no": line.line_no, **finding})
            results.append(
                {
                    "line_no": line.line_no,
                    "description": line.description,
                    "matched": True,
                    "contract_term_id": str(term.id),
                    "product_code": term.product_code,
                    "quantity": str(quantity),
                    "quantity_within_bounds": quantity_ok,
                    "billed_unit_price": str(billed_price),
                    "contract_unit_price": str(contract_price),
                    "variance_amount": comparison["variance_amount"],
                    "variance_pct": comparison["variance_pct"],
                    "billed_total": str(billed_line),
                    "expected_total": str(expected_line),
                    "line_total_variance": str(total_variance),
                }
            )

        total_variance = (billed_total - expected_total).quantize(Decimal("0.01"))
        variance_pct = (
            float((total_variance / expected_total) * 100) if expected_total else None
        )
        return {
            "invoice_id": str(invoice.id),
            "invoice_number": invoice.invoice_number,
            "contract_id": str(contract.id),
            "contract_number": contract.contract_number,
            "contract_version_id": contract_version_id,
            "invoice_date": invoice_date.isoformat(),
            "lines": results,
            "totals": {
                "billed_total": str(billed_total),
                "expected_total": str(expected_total),
                "variance_amount": str(total_variance),
                "variance_pct": variance_pct,
                "currency": invoice.currency,
                "within_tolerance": abs(total_variance) <= PRICE_TOLERANCE,
            },
            "findings": findings,
            "methodology": (
                "Invoice lines match contract terms effective on the invoice "
                "date by product_code then normalized description. Unit price, "
                "quantity bounds, and line totals use Decimal arithmetic with a "
                f"{PRICE_TOLERANCE} absolute price tolerance."
            ),
            "summary": (
                f"{invoice.invoice_number}: {len(findings)} findings, "
                f"variance {total_variance} {invoice.currency}"
            ),
        }


@procurement.tool("get_maverick_spend")
async def get_maverick_spend(context, arguments: dict[str, Any]) -> dict[str, Any]:
    """Return unmanaged SaaS detections with employee and overlap context."""
    status = arguments.get("status") or "open"
    days = int(arguments.get("days") or 90)
    min_score = arguments.get("min_score")
    limit = int(arguments.get("limit") or 25)
    offset = int(arguments.get("offset") or 0)
    cutoff = datetime.now(UTC) - timedelta(days=days)

    async with async_session_context() as session:
        stmt = (
            select(MaverickAlert, CardTransaction, Employee, Department, ContractProductProfile)
            .join(CardTransaction, CardTransaction.id == MaverickAlert.transaction_id)
            .outerjoin(Employee, Employee.id == MaverickAlert.employee_id)
            .outerjoin(Department, Department.id == Employee.department_id)
            .outerjoin(
                ContractProductProfile,
                ContractProductProfile.id == MaverickAlert.overlap_catalog_id,
            )
            .where(
                MaverickAlert.tenant_id == context.tenant_id,
                CardTransaction.txn_date >= cutoff,
            )
        )
        if status != "all":
            stmt = stmt.where(MaverickAlert.status == AlertStatus(status))
        if min_score is not None:
            stmt = stmt.where(MaverickAlert.jev_is_saas_score >= Decimal(str(min_score)))
        total = await session.scalar(
            select(func.count()).select_from(stmt.subquery())
        )
        rows = (
            await session.execute(
                stmt.order_by(
                    MaverickAlert.jev_is_saas_score.desc().nulls_last(),
                    CardTransaction.txn_date.desc(),
                )
                .limit(limit)
                .offset(offset)
            )
        ).all()
        detections = [
            {
                "id": str(alert.id),
                "merchant_name": alert.merchant_name,
                "amount": _money(transaction.amount),
                "currency": transaction.currency,
                "txn_date": _iso(transaction.txn_date),
                "saaS_score": _ratio(alert.jev_is_saas_score),
                "review_score": _ratio(alert.jev_review_score),
                "status": _enum(alert.status),
                "recommended_action": alert.recommended_action,
                "overlap_score": _ratio(alert.overlap_score),
                "overlap_product": (
                    profile.product_name if profile else None
                ),
                "capability_text": alert.capability_text,
                "employee": (
                    {
                        "id": str(employee.id),
                        "name": employee.display_name,
                        "email": employee.email,
                        "department": department.name if department else employee.department_raw,
                    }
                    if employee
                    else None
                ),
                "cardholder": transaction.cardholder_name_raw,
            }
            for alert, transaction, employee, department, profile in rows
        ]
        return {
            "detections": detections,
            "count": len(detections),
            "total": int(total or 0),
            "pagination": {"limit": limit, "offset": offset},
            "as_of": datetime.now(UTC).isoformat(),
            "summary": f"{len(detections)} of {int(total or 0)} maverick detections",
        }


@procurement.tool("get_spend_trend")
async def get_spend_trend(context, arguments: dict[str, Any]) -> dict[str, Any]:
    """Return a monthly or weekly spend series across invoices and cards."""
    start, end = _window(arguments.get("start_date"), arguments.get("end_date"))
    if end is None:
        end = datetime.now(UTC)
    if start is None:
        start = end - timedelta(days=365)
    granularity = arguments.get("granularity") or "month"
    source = arguments.get("source") or "both"
    vendor_id = (
        _uuid(arguments["vendor_id"], "vendor_id") if arguments.get("vendor_id") else None
    )
    bucket = "month" if granularity == "month" else "week"

    async with async_session_context() as session:
        series: dict[str, dict[str, Decimal]] = defaultdict(
            lambda: {"invoices": _ZERO, "card_transactions": _ZERO}
        )
        currencies: list[str] = []
        if source in {"invoices", "both"}:
            stmt = select(
                func.date_trunc(bucket, Invoice.invoice_date).label("bucket"),
                func.sum(Invoice.total_amount),
            ).where(
                Invoice.tenant_id == context.tenant_id,
                Invoice.invoice_date >= start,
                Invoice.invoice_date <= end,
            )
            if vendor_id:
                stmt = stmt.where(Invoice.vendor_id == vendor_id)
            for bucket_value, amount in (
                await session.execute(stmt.group_by("bucket").order_by("bucket"))
            ).all():
                series[bucket_value.date().isoformat()]["invoices"] += to_decimal(amount)
        if source in {"card_transactions", "both"}:
            stmt = select(
                func.date_trunc(bucket, CardTransaction.txn_date).label("bucket"),
                func.sum(CardTransaction.amount),
            ).where(
                CardTransaction.tenant_id == context.tenant_id,
                CardTransaction.txn_date >= start,
                CardTransaction.txn_date <= end,
            )
            if vendor_id:
                stmt = stmt.where(CardTransaction.vendor_id == vendor_id)
            for bucket_value, amount in (
                await session.execute(stmt.group_by("bucket").order_by("bucket"))
            ).all():
                series[bucket_value.date().isoformat()]["card_transactions"] += to_decimal(amount)
        if vendor_id:
            currencies = list(
                (
                    await session.scalars(
                        select(Invoice.currency).where(
                            Invoice.tenant_id == context.tenant_id,
                            Invoice.vendor_id == vendor_id,
                        ).limit(20)
                    )
                ).all()
            )
        points = [
            {
                "period": period,
                "invoices": _money(values["invoices"]),
                "card_transactions": _money(values["card_transactions"]),
                "total": _money(values["invoices"] + values["card_transactions"]),
            }
            for period, values in sorted(series.items())
        ]
        total = sum((to_decimal(point["total"]) for point in points), _ZERO)
        return {
            "series": points,
            "total": _money(total),
            "currency": _currency(currencies),
            "period": {"start_date": start.date().isoformat(), "end_date": end.date().isoformat()},
            "granularity": bucket,
            "source": source,
            "as_of": datetime.now(UTC).isoformat(),
            "summary": f"{len(points)} {bucket} periods, total {_money(total)}",
        }


@procurement.tool("calculate_spend")
async def calculate_spend(context, arguments: dict[str, Any]) -> dict[str, Any]:
    """Calculate authoritative spend with optional filters and grouping."""
    start, end = _window(arguments["start_date"], arguments["end_date"])
    assert start is not None and end is not None
    source = arguments.get("source") or "both"
    group_by = arguments.get("group_by") or "vendor"
    vendor_id = (
        _uuid(arguments["vendor_id"], "vendor_id") if arguments.get("vendor_id") else None
    )
    category = arguments.get("category")

    async with async_session_context() as session:
        totals: dict[str, Decimal] = defaultdict(lambda: _ZERO)
        display: dict[str, str] = {}
        currencies: list[str] = []
        grand_total = _ZERO

        async def add_invoices() -> None:
            nonlocal grand_total
            stmt = (
                select(Invoice, Vendor)
                .outerjoin(Vendor, Vendor.id == Invoice.vendor_id)
                .where(
                    Invoice.tenant_id == context.tenant_id,
                    Invoice.invoice_date >= start,
                    Invoice.invoice_date <= end,
                )
            )
            if vendor_id:
                stmt = stmt.where(Invoice.vendor_id == vendor_id)
            if category:
                stmt = stmt.where(Vendor.category == category)
            for invoice, vendor in (await session.execute(stmt)).all():
                amount = to_decimal(invoice.total_amount)
                grand_total += amount
                currencies.append(invoice.currency)
                key, label = _spend_group_key(group_by, invoice, vendor, None)
                totals[key] += amount
                display[key] = label

        async def add_cards() -> None:
            nonlocal grand_total
            stmt = (
                select(CardTransaction, Vendor, Department)
                .outerjoin(Vendor, Vendor.id == CardTransaction.vendor_id)
                .outerjoin(Department, Department.id == CardTransaction.department_id)
                .where(
                    CardTransaction.tenant_id == context.tenant_id,
                    CardTransaction.txn_date >= start,
                    CardTransaction.txn_date <= end,
                )
            )
            if vendor_id:
                stmt = stmt.where(CardTransaction.vendor_id == vendor_id)
            if category:
                stmt = stmt.where(
                    or_(Vendor.category == category, CardTransaction.sk_category_name == category)
                )
            for transaction, vendor, department in (await session.execute(stmt)).all():
                amount = to_decimal(transaction.amount)
                grand_total += amount
                currencies.append(transaction.currency)
                key, label = _spend_group_key(group_by, transaction, vendor, department)
                totals[key] += amount
                display[key] = label

        if source in {"invoices", "both"}:
            await add_invoices()
        if source in {"card_transactions", "both"}:
            await add_cards()

        breakdown = [
            {"key": key, "label": display[key], "amount": _money(amount)}
            for key, amount in sorted(totals.items(), key=lambda item: item[1], reverse=True)
        ]
        return {
            "total": _money(grand_total),
            "currency": _currency(currencies),
            "group_by": group_by,
            "breakdown": breakdown,
            "filters": {
                "start_date": arguments["start_date"],
                "end_date": arguments["end_date"],
                "vendor_id": str(vendor_id) if vendor_id else None,
                "category": category,
                "source": source,
            },
            "period": {
                "start_date": start.date().isoformat(),
                "end_date": end.date().isoformat(),
            },
            "methodology": (
                "Sum of invoice.total_amount and card_transaction.amount. "
                "Invoices have no department allocation; those rows group under "
                "'unallocated'. No FX normalization is applied."
            ),
            "as_of": datetime.now(UTC).isoformat(),
            "summary": f"total {_money(grand_total)} grouped by {group_by}",
        }


def _spend_group_key(
    group_by: str,
    row: Any,
    vendor: Vendor | None,
    department: Department | None,
) -> tuple[str, str]:
    """Return the stable grouping key and display label for one spend row."""
    if group_by == "month":
        occurred = getattr(row, "invoice_date", None) or getattr(row, "txn_date")
        key = occurred.strftime("%Y-%m")
        return key, key
    if group_by == "category":
        category = (
            vendor.category
            if vendor and vendor.category
            else getattr(row, "sk_category_name", None) or "uncategorized"
        )
        return str(category), str(category)
    if group_by == "department":
        if department is not None:
            return str(department.id), department.name
        return "unallocated", "Unallocated"
    if vendor is not None:
        return str(vendor.id), vendor.name
    name = getattr(row, "merchant_name", None) or "unattributed"
    return f"merchant:{name}", name


@procurement.tool("calculate_savings")
async def calculate_savings(context, arguments: dict[str, Any]) -> dict[str, Any]:
    """Calculate verified savings and potential recovery opportunities."""
    vendor_id = (
        _uuid(arguments["vendor_id"], "vendor_id") if arguments.get("vendor_id") else None
    )
    start, end = _window(arguments.get("start_date"), arguments.get("end_date"))
    include_opportunities = arguments.get("include_opportunities", True)

    async with async_session_context() as session:
        ledger_stmt = select(SavingsLedgerEntry).where(
            SavingsLedgerEntry.tenant_id == context.tenant_id
        )
        if vendor_id:
            ledger_stmt = ledger_stmt.where(SavingsLedgerEntry.vendor_id == vendor_id)
        if start:
            ledger_stmt = ledger_stmt.where(SavingsLedgerEntry.created_at >= start)
        if end:
            ledger_stmt = ledger_stmt.where(SavingsLedgerEntry.created_at <= end)
        entries = (await session.scalars(ledger_stmt)).all()

        verified_hard = _ZERO
        verified_avoidance = _ZERO
        potential_ledger = _ZERO
        components: list[dict[str, Any]] = []
        currencies: list[str] = [entry.currency for entry in entries]
        for entry in entries:
            amount = to_decimal(entry.amount)
            kind = _enum(entry.kind)
            status = _enum(entry.status)
            if status == SavingsStatus.VERIFIED.value and kind == "hard_cash":
                verified_hard += amount
            elif status == SavingsStatus.VERIFIED.value and kind == "avoidance":
                verified_avoidance += amount
            else:
                potential_ledger += amount
            components.append(
                {
                    "source_type": entry.source_type,
                    "source_id": str(entry.source_id),
                    "kind": kind,
                    "status": status,
                    "amount": _money(amount),
                    "notes": entry.notes,
                }
            )

        potential_overbilling = _ZERO
        potential_shelfware = _ZERO
        if include_opportunities:
            exception_stmt = select(ReconciliationException).where(
                ReconciliationException.tenant_id == context.tenant_id,
                ReconciliationException.status == ExceptionStatus.OPEN,
                ReconciliationException.variance_amount > 0,
            )
            if vendor_id:
                exception_stmt = exception_stmt.join(
                    Invoice, Invoice.id == ReconciliationException.invoice_id
                ).where(Invoice.vendor_id == vendor_id)
            for exception in (await session.scalars(exception_stmt)).all():
                potential_overbilling += to_decimal(exception.variance_amount)
            forecast_stmt = select(SeatForecast).where(
                SeatForecast.tenant_id == context.tenant_id
            )
            if vendor_id:
                forecast_stmt = forecast_stmt.where(SeatForecast.vendor_id == vendor_id)
            seen: set[uuid.UUID] = set()
            for forecast in (
                await session.scalars(
                    forecast_stmt.order_by(
                        SeatForecast.forecast_date.desc(), SeatForecast.created_at.desc()
                    )
                )
            ).all():
                if forecast.vendor_id in seen:
                    continue
                seen.add(forecast.vendor_id)
                potential_shelfware += to_decimal(forecast.shelfware_amount)

        return {
            "verified_hard_cash": _money(verified_hard),
            "verified_avoidance": _money(verified_avoidance),
            "potential_ledger": _money(potential_ledger),
            "potential_overbilling": _money(potential_overbilling),
            "potential_shelfware": _money(potential_shelfware),
            "currency": _currency(currencies),
            "components": components,
            "period": {
                "start_date": arguments.get("start_date"),
                "end_date": arguments.get("end_date"),
            },
            "methodology": (
                "Verified values come from savings_ledger_entries with "
                "status=verified. Overbilling is the positive variance on open "
                "reconciliation exceptions. Shelfware is the latest seat "
                "forecast per vendor; it is an opportunity, not booked savings."
            ),
            "as_of": datetime.now(UTC).isoformat(),
            "summary": (
                f"verified {_money(verified_hard + verified_avoidance)}, "
                f"potential {_money(potential_overbilling + potential_shelfware)}"
            ),
        }


__all__ = ["SERVER_NAME", "SERVER_VERSION", "procurement"]
