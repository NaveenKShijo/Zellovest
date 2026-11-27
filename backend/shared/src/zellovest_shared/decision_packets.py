"""Pre-computed procurement decision packets and live commercial context builders.

These helpers assemble deterministic, evidence-backed decision packets for:
- AP audit reconciliation exceptions (``ap_investigation``)
- Upcoming contract renewals & notice deadlines (``renewal_dossier``)
- Unmanaged / maverick SaaS alerts (``maverick_review``)

All financial arithmetic uses :class:`decimal.Decimal`; AI/RAG synthesis is
strictly additive and clearly separated from confirmed facts and calculations.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from zellovest_shared.db.core import Department, Employee, Vendor
from zellovest_shared.db.intelligence import (
    AlertStatus,
    DecisionPacket,
    ExceptionStatus,
    LicenseAssignment,
    MaverickAlert,
    ReconciliationException,
    SeatForecast,
    UsageEvent,
)
from zellovest_shared.db.transact import (
    CardTransaction,
    Contract,
    ContractStatus,
    ContractTermsVersion,
    ContractVersion,
    Document,
    Invoice,
    InvoiceLineItem,
    PurchaseOrder,
)
from zellovest_shared.logging_conf import get_logger
from zellovest_shared.pricing import to_decimal

logger = get_logger(__name__)

PACKET_AP_INVESTIGATION = "ap_investigation"
PACKET_RENEWAL_DOSSIER = "renewal_dossier"
PACKET_MAVERICK_REVIEW = "maverick_review"

ENTITY_EXCEPTION = "reconciliation_exception"
ENTITY_CONTRACT = "contract"
ENTITY_MAVERICK_ALERT = "maverick_alert"

STATUS_PENDING_REVIEW = "pending_review"
STATUS_ACTIONED = "actioned"
STATUS_DISMISSED = "dismissed"


def compute_source_hash(payload: Any) -> str:
    """Return a stable SHA-256 hex digest for source state fingerprinting."""
    encoded = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _safe_rag_search(
    *,
    tenant_id: str,
    query: str,
    vendor_id: str | None = None,
    document_type: str | None = None,
    document_types: list[str] | None = None,
    limit: int = 4,
) -> list[dict[str, Any]]:
    """Run hybrid RAG retrieval without raising when Qdrant/Voyage is unavailable."""
    try:
        from zellovest_shared.rag import search_documents

        return search_documents(
            tenant_id=tenant_id,
            query=query[:1500],
            vendor_id=vendor_id,
            document_type=document_type,
            document_types=document_types,
            limit=limit,
        )
    except Exception as exc:
        logger.info(
            "decision_packet_rag_unavailable",
            tenant_id=tenant_id,
            vendor_id=vendor_id,
            error_class=type(exc).__name__,
        )
        return []


def compute_vendor_utilization_sync(
    session: Session,
    tenant_id: str,
    vendor_id: uuid.UUID,
) -> dict[str, Any]:
    """Compute live license utilization and latest forecast metrics for one vendor."""
    now = datetime.now(UTC)
    cutoff_30d = now - timedelta(days=30)
    cutoff_90d = now - timedelta(days=90)

    assigned_rows = session.execute(
        select(
            func.coalesce(func.sum(LicenseAssignment.seats), 0),
            func.count(func.distinct(LicenseAssignment.employee_id)),
        ).where(
            LicenseAssignment.tenant_id == tenant_id,
            LicenseAssignment.vendor_id == vendor_id,
            LicenseAssignment.status == "active",
        )
    ).one()
    purchased_seats = int(assigned_rows[0] or 0)
    assigned_employees = int(assigned_rows[1] or 0)

    active_30d = int(
        session.scalar(
            select(func.count(func.distinct(UsageEvent.employee_id))).where(
                UsageEvent.tenant_id == tenant_id,
                UsageEvent.vendor_id == vendor_id,
                UsageEvent.occurred_at >= cutoff_30d,
                UsageEvent.employee_id.is_not(None),
            )
        )
        or 0
    )
    active_90d = int(
        session.scalar(
            select(func.count(func.distinct(UsageEvent.employee_id))).where(
                UsageEvent.tenant_id == tenant_id,
                UsageEvent.vendor_id == vendor_id,
                UsageEvent.occurred_at >= cutoff_90d,
                UsageEvent.employee_id.is_not(None),
            )
        )
        or 0
    )

    latest_forecasts = (
        session.execute(
            select(SeatForecast)
            .where(
                SeatForecast.tenant_id == tenant_id,
                SeatForecast.vendor_id == vendor_id,
            )
            .order_by(SeatForecast.forecast_date.desc(), SeatForecast.created_at.desc())
        )
        .scalars()
        .all()
    )

    latest_by_dept: dict[str, SeatForecast] = {}
    for row in latest_forecasts:
        dept_key = row.department or "All"
        if dept_key not in latest_by_dept:
            latest_by_dept[dept_key] = row

    forecast_current = sum(f.current_seats for f in latest_by_dept.values())
    forecast_recommended = sum(f.recommended_seats for f in latest_by_dept.values())
    forecast_savings = sum(float(f.savings_estimate or 0.0) for f in latest_by_dept.values())
    forecast_shelfware = sum(float(f.shelfware_amount or 0.0) for f in latest_by_dept.values())
    forecast_trueup_risk = sum(float(f.trueup_risk_amount or 0.0) for f in latest_by_dept.values())

    seat_denominator = purchased_seats or forecast_current
    active_basis = active_30d or active_90d
    if seat_denominator > 0 and active_basis > 0:
        utilization_pct = round(min(100.0, (active_basis / seat_denominator) * 100.0), 1)
        unused_seats = max(0, seat_denominator - active_basis)
    elif forecast_current > 0 and forecast_recommended <= forecast_current:
        utilization_pct = round((forecast_recommended / forecast_current) * 100.0, 1)
        unused_seats = max(0, forecast_current - forecast_recommended)
    else:
        utilization_pct = None
        unused_seats = 0

    return {
        "purchased_seats": seat_denominator,
        "assigned_employees": assigned_employees,
        "active_users_30d": active_30d,
        "active_users_90d": active_90d,
        "idle_seats": unused_seats,
        "utilization_pct": utilization_pct,
        "forecast_current_seats": forecast_current,
        "forecast_recommended_seats": forecast_recommended,
        "forecast_savings_estimate": round(forecast_savings, 2),
        "forecast_shelfware_amount": round(forecast_shelfware, 2),
        "forecast_trueup_risk_amount": round(forecast_trueup_risk, 2),
        "has_forecast": bool(latest_by_dept),
        "has_telemetry": seat_denominator > 0 or active_90d > 0,
    }


async def acompute_vendor_utilization(
    session: AsyncSession,
    tenant_id: str,
    vendor_id: uuid.UUID,
) -> dict[str, Any]:
    """Async counterpart to :func:`compute_vendor_utilization_sync`."""
    now = datetime.now(UTC)
    cutoff_30d = now - timedelta(days=30)
    cutoff_90d = now - timedelta(days=90)

    assigned_res = await session.execute(
        select(
            func.coalesce(func.sum(LicenseAssignment.seats), 0),
            func.count(func.distinct(LicenseAssignment.employee_id)),
        ).where(
            LicenseAssignment.tenant_id == tenant_id,
            LicenseAssignment.vendor_id == vendor_id,
            LicenseAssignment.status == "active",
        )
    )
    assigned_rows = assigned_res.one()
    purchased_seats = int(assigned_rows[0] or 0)
    assigned_employees = int(assigned_rows[1] or 0)

    active_30d = int(
        (
            await session.scalar(
                select(func.count(func.distinct(UsageEvent.employee_id))).where(
                    UsageEvent.tenant_id == tenant_id,
                    UsageEvent.vendor_id == vendor_id,
                    UsageEvent.occurred_at >= cutoff_30d,
                    UsageEvent.employee_id.is_not(None),
                )
            )
        )
        or 0
    )
    active_90d = int(
        (
            await session.scalar(
                select(func.count(func.distinct(UsageEvent.employee_id))).where(
                    UsageEvent.tenant_id == tenant_id,
                    UsageEvent.vendor_id == vendor_id,
                    UsageEvent.occurred_at >= cutoff_90d,
                    UsageEvent.employee_id.is_not(None),
                )
            )
        )
        or 0
    )

    forecast_res = await session.execute(
        select(SeatForecast)
        .where(
            SeatForecast.tenant_id == tenant_id,
            SeatForecast.vendor_id == vendor_id,
        )
        .order_by(SeatForecast.forecast_date.desc(), SeatForecast.created_at.desc())
    )
    latest_forecasts = forecast_res.scalars().all()
    latest_by_dept: dict[str, SeatForecast] = {}
    for row in latest_forecasts:
        dept_key = row.department or "All"
        if dept_key not in latest_by_dept:
            latest_by_dept[dept_key] = row

    forecast_current = sum(f.current_seats for f in latest_by_dept.values())
    forecast_recommended = sum(f.recommended_seats for f in latest_by_dept.values())
    forecast_savings = sum(float(f.savings_estimate or 0.0) for f in latest_by_dept.values())
    forecast_shelfware = sum(float(f.shelfware_amount or 0.0) for f in latest_by_dept.values())
    forecast_trueup_risk = sum(float(f.trueup_risk_amount or 0.0) for f in latest_by_dept.values())

    seat_denominator = purchased_seats or forecast_current
    active_basis = active_30d or active_90d
    if seat_denominator > 0 and active_basis > 0:
        utilization_pct = round(min(100.0, (active_basis / seat_denominator) * 100.0), 1)
        unused_seats = max(0, seat_denominator - active_basis)
    elif forecast_current > 0 and forecast_recommended <= forecast_current:
        utilization_pct = round((forecast_recommended / forecast_current) * 100.0, 1)
        unused_seats = max(0, forecast_current - forecast_recommended)
    else:
        utilization_pct = None
        unused_seats = 0

    return {
        "purchased_seats": seat_denominator,
        "assigned_employees": assigned_employees,
        "active_users_30d": active_30d,
        "active_users_90d": active_90d,
        "idle_seats": unused_seats,
        "utilization_pct": utilization_pct,
        "forecast_current_seats": forecast_current,
        "forecast_recommended_seats": forecast_recommended,
        "forecast_savings_estimate": round(forecast_savings, 2),
        "forecast_shelfware_amount": round(forecast_shelfware, 2),
        "forecast_trueup_risk_amount": round(forecast_trueup_risk, 2),
        "has_forecast": bool(latest_by_dept),
        "has_telemetry": seat_denominator > 0 or active_90d > 0,
    }


def upsert_decision_packet_sync(
    session: Session,
    *,
    tenant_id: str,
    packet_type: str,
    entity_type: str,
    entity_id: uuid.UUID,
    vendor_id: uuid.UUID | None,
    title: str,
    summary: str,
    recommended_action: str | None,
    financial_impact: Decimal | float | None,
    currency: str,
    urgency_date: date | None,
    source_hash: str,
    payload: dict[str, Any],
    default_status: str = STATUS_PENDING_REVIEW,
) -> DecisionPacket:
    """Idempotently create or update one pre-computed decision packet."""
    existing = session.scalar(
        select(DecisionPacket).where(
            DecisionPacket.tenant_id == tenant_id,
            DecisionPacket.packet_type == packet_type,
            DecisionPacket.entity_id == entity_id,
        )
    )
    impact_val = (
        float(to_decimal(financial_impact).quantize(Decimal("0.01")))
        if financial_impact is not None
        else None
    )
    if existing is not None:
        if existing.source_hash == source_hash:
            return existing
        existing.vendor_id = vendor_id
        existing.title = title[:256]
        existing.summary = summary
        existing.recommended_action = recommended_action
        existing.financial_impact = impact_val
        existing.currency = (currency or "USD")[:8]
        existing.urgency_date = urgency_date
        existing.source_hash = source_hash
        existing.payload = payload
        # Re-open only if source state changed meaningfully while previously pending
        if existing.status not in (STATUS_ACTIONED, STATUS_DISMISSED):
            existing.status = default_status
        session.flush()
        return existing

    packet = DecisionPacket(
        tenant_id=tenant_id,
        packet_type=packet_type,
        entity_type=entity_type,
        entity_id=entity_id,
        vendor_id=vendor_id,
        title=title[:256],
        summary=summary,
        recommended_action=recommended_action,
        financial_impact=impact_val,
        currency=(currency or "USD")[:8],
        urgency_date=urgency_date,
        source_hash=source_hash,
        payload=payload,
        status=default_status,
    )
    session.add(packet)
    session.flush()
    return packet


async def aupsert_decision_packet(
    session: AsyncSession,
    *,
    tenant_id: str,
    packet_type: str,
    entity_type: str,
    entity_id: uuid.UUID,
    vendor_id: uuid.UUID | None,
    title: str,
    summary: str,
    recommended_action: str | None,
    financial_impact: Decimal | float | None,
    currency: str,
    urgency_date: date | None,
    source_hash: str,
    payload: dict[str, Any],
    default_status: str = STATUS_PENDING_REVIEW,
) -> DecisionPacket:
    """Async counterpart to :func:`upsert_decision_packet_sync`."""
    existing = await session.scalar(
        select(DecisionPacket).where(
            DecisionPacket.tenant_id == tenant_id,
            DecisionPacket.packet_type == packet_type,
            DecisionPacket.entity_id == entity_id,
        )
    )
    impact_val = (
        float(to_decimal(financial_impact).quantize(Decimal("0.01")))
        if financial_impact is not None
        else None
    )
    if existing is not None:
        if existing.source_hash == source_hash:
            return existing
        existing.vendor_id = vendor_id
        existing.title = title[:256]
        existing.summary = summary
        existing.recommended_action = recommended_action
        existing.financial_impact = impact_val
        existing.currency = (currency or "USD")[:8]
        existing.urgency_date = urgency_date
        existing.source_hash = source_hash
        existing.payload = payload
        if existing.status not in (STATUS_ACTIONED, STATUS_DISMISSED):
            existing.status = default_status
        await session.flush()
        return existing

    packet = DecisionPacket(
        tenant_id=tenant_id,
        packet_type=packet_type,
        entity_type=entity_type,
        entity_id=entity_id,
        vendor_id=vendor_id,
        title=title[:256],
        summary=summary,
        recommended_action=recommended_action,
        financial_impact=impact_val,
        currency=(currency or "USD")[:8],
        urgency_date=urgency_date,
        source_hash=source_hash,
        payload=payload,
        status=default_status,
    )
    session.add(packet)
    await session.flush()
    return packet


def build_ap_investigation_packet_sync(
    session: Session,
    tenant_id: str,
    exception_id: uuid.UUID,
    *,
    rag_search: Callable[..., list[dict[str, Any]]] | None = None,
) -> DecisionPacket | None:
    """Pre-compute an evidence-backed investigation packet for an AP exception."""
    exc = session.scalar(
        select(ReconciliationException).where(
            ReconciliationException.id == exception_id,
            ReconciliationException.tenant_id == tenant_id,
        )
    )
    if exc is None:
        return None

    invoice = session.get(Invoice, exc.invoice_id)
    if invoice is None:
        return None
    vendor = session.get(Vendor, invoice.vendor_id) if invoice.vendor_id else None
    contract = session.get(Contract, exc.contract_id) if exc.contract_id else None
    term = session.get(ContractTermsVersion, exc.contract_term_id) if exc.contract_term_id else None
    inv_line = session.get(InvoiceLineItem, exc.invoice_line_id) if exc.invoice_line_id else None
    po = (
        session.get(PurchaseOrder, exc.po_id or invoice.po_id)
        if (exc.po_id or invoice.po_id)
        else None
    )

    vendor_name = vendor.name if vendor else "Unknown Vendor"
    contract_num = contract.contract_number if contract else "Unknown Contract"
    rule_val = exc.rule_type.value if hasattr(exc.rule_type, "value") else str(exc.rule_type)

    prior_invoices = (
        session.execute(
            select(Invoice)
            .where(
                Invoice.tenant_id == tenant_id,
                Invoice.vendor_id == invoice.vendor_id,
                Invoice.id != invoice.id,
                Invoice.invoice_date <= invoice.invoice_date,
            )
            .order_by(Invoice.invoice_date.desc())
            .limit(10)
        )
        .scalars()
        .all()
    )
    prior_cards = (
        session.execute(
            select(CardTransaction)
            .where(
                CardTransaction.tenant_id == tenant_id,
                CardTransaction.vendor_id == invoice.vendor_id,
            )
            .order_by(CardTransaction.txn_date.desc())
            .limit(10)
        )
        .scalars()
        .all()
    )
    versions = (
        session.execute(
            select(ContractVersion)
            .where(
                ContractVersion.tenant_id == tenant_id,
                ContractVersion.contract_id == exc.contract_id,
            )
            .order_by(ContractVersion.version_no.asc())
        )
        .scalars()
        .all()
    )
    term_history = (
        session.execute(
            select(ContractTermsVersion)
            .where(
                ContractTermsVersion.tenant_id == tenant_id,
                ContractTermsVersion.contract_id == exc.contract_id,
            )
            .order_by(ContractTermsVersion.effective_from.asc())
        )
        .scalars()
        .all()
    )

    citations: list[dict[str, Any]] = [
        {
            "tool": "ap_audit_engine",
            "source_id": str(exc.id),
            "document_id": str(invoice.document_id) if invoice.document_id else None,
            "page": None,
            "section": f"Invoice {invoice.invoice_number}",
            "excerpt": None,
        }
    ]
    if contract and contract.document_id:
        citations.append(
            {
                "tool": "contract_ledger",
                "source_id": str(contract.id),
                "document_id": str(contract.document_id),
                "page": None,
                "section": f"Contract {contract_num}",
                "excerpt": None,
            }
        )

    confirmed_facts: list[dict[str, Any]] = [
        {
            "statement": (
                f"Invoice {invoice.invoice_number} from {vendor_name} is linked to "
                f"contract {contract_num} and triggered rule '{rule_val}'."
            ),
            "citations": [citations[0]],
        },
        {
            "statement": (
                f"Commercial history contains {len(prior_invoices)} prior invoice(s), "
                f"{len(prior_cards)} vendor-linked card transaction(s), and "
                f"{len(versions)} contract version(s)."
            ),
            "citations": [citations[0]],
        },
    ]
    if po is not None:
        confirmed_facts.append(
            {
                "statement": f"Linked to Purchase Order {po.po_number} (authorized ceiling ${float(po.total_amount):,.2f}).",
                "citations": [citations[0]],
            }
        )

    variance_dec = abs(to_decimal(exc.variance_amount))
    expected_dec = to_decimal(exc.expected_value)
    billed_dec = to_decimal(exc.billed_value)
    pct_text = f"{float(exc.variance_pct):.2f}%" if exc.variance_pct is not None else "n/a"

    calculated_values: list[dict[str, Any]] = [
        {
            "statement": (
                f"Deterministic audit compared billed value ${billed_dec:,.2f} against "
                f"contracted expectation ${expected_dec:,.2f}, yielding variance "
                f"${variance_dec:,.2f} ({pct_text})."
            ),
            "citations": [citations[0]],
        }
    ]
    if inv_line is not None and term is not None:
        calculated_values.append(
            {
                "statement": (
                    f"Line #{inv_line.line_no} ({inv_line.description or term.description}): "
                    f"billed {inv_line.quantity} units at ${to_decimal(inv_line.unit_price):,.2f} "
                    f"vs contract term ${to_decimal(term.unit_price):,.2f}."
                ),
                "citations": [citations[0]],
            }
        )

    possible_explanations: list[dict[str, Any]] = []
    needs_human_review: list[dict[str, Any]] = []
    if po is None and rule_val == "missing_po":
        needs_human_review.append(
            {
                "statement": "No authorized Purchase Order is linked to this invoice; verify if a PO was issued outside the ledger.",
                "citations": [citations[0]],
            }
        )

    if term is not None:
        other_terms = [
            t
            for t in term_history
            if t.id != term.id
            and (not term.contract_line_id or t.contract_line_id == term.contract_line_id)
        ]
        for prior_t in other_terms[-3:]:
            possible_explanations.append(
                {
                    "statement": (
                        f"Another contract term version specifies unit price ${to_decimal(prior_t.unit_price):,.2f} "
                        f"(qty {prior_t.qty_min or 0}-{prior_t.qty_max or 'unbounded'}) effective "
                        f"{prior_t.effective_from.isoformat()} to "
                        f"{prior_t.effective_to.isoformat() if prior_t.effective_to else 'open-ended'}."
                    ),
                    "citations": [citations[-1]],
                }
            )

    search_fn = rag_search or _safe_rag_search
    subject = (
        (term.product_code if term else None)
        or (term.description if term else None)
        or vendor_name
    )
    rag_chunks = search_fn(
        tenant_id=tenant_id,
        query=f"amendment pricing seats escalation {subject}",
        vendor_id=str(invoice.vendor_id) if invoice.vendor_id else None,
        document_types=["amendment", "contract"],
        limit=3,
    )
    existing_doc_ids = {
        str(row_id)
        for row_id in session.execute(
            select(Document.id).where(Document.tenant_id == tenant_id)
        )
        .scalars()
        .all()
    }
    for chunk in rag_chunks:
        doc_id = str(chunk.get("document_id") or "")
        if doc_id and doc_id not in existing_doc_ids:
            continue
        cit = {
            "tool": "document_knowledge_rag",
            "source_id": str(chunk.get("chunk_id") or "") or None,
            "document_id": doc_id or None,
            "page": chunk.get("page") if isinstance(chunk.get("page"), int) else None,
            "section": str(chunk.get("section") or "") or None,
            "excerpt": str(chunk.get("content") or chunk.get("parent_content") or "")[:400],
        }
        citations.append(cit)
        possible_explanations.append(
            {
                "statement": (
                    f"Source clause in {chunk.get('filename') or 'contract document'} "
                    f"(p.{chunk.get('page') or '?'}) discusses pricing/amendment terms."
                ),
                "citations": [cit],
            }
        )

    if rule_val in {"price", "discount", "freight", "tax"}:
        recommended_action = (
            f"Dispute overcharge of ${variance_dec:,.2f} on {invoice.invoice_number} "
            f"and log potential hard-cash recovery."
        )
    elif rule_val == "missing_po":
        recommended_action = (
            f"Verify PO authorization for {invoice.invoice_number} (${float(invoice.total_amount):,.2f}) "
            "before payment approval."
        )
    else:
        recommended_action = (
            f"Review {rule_val.replace('_', ' ')} variance of ${variance_dec:,.2f} "
            f"against {contract_num} before releasing payment."
        )

    summary = (
        f"{invoice.invoice_number} ({vendor_name}) flagged for {rule_val.replace('_', ' ')}: "
        f"${variance_dec:,.2f} variance vs {contract_num}. "
        f"{len(confirmed_facts)} confirmed fact(s), {len(rag_chunks)} contract passage(s) attached."
    )
    source_hash = compute_source_hash(
        {
            "exc_id": str(exc.id),
            "status": exc.status.value,
            "variance": str(variance_dec),
            "contract_id": str(exc.contract_id),
            "versions": len(versions),
            "rag_ids": [c.get("source_id") for c in citations],
        }
    )
    payload = {
        "exception_id": str(exc.id),
        "invoice_id": str(invoice.id),
        "invoice_number": invoice.invoice_number,
        "vendor_id": str(invoice.vendor_id) if invoice.vendor_id else None,
        "vendor_name": vendor_name,
        "contract_id": str(exc.contract_id),
        "contract_number": contract_num,
        "rule_type": rule_val,
        "severity": exc.severity,
        "summary": summary,
        "confirmed_facts": confirmed_facts,
        "calculated_values": calculated_values,
        "possible_explanations": possible_explanations,
        "needs_human_review": needs_human_review,
        "citations": citations,
        "data_gaps": [],
        "generated_at": datetime.now(UTC).isoformat(),
    }
    packet_status = (
        STATUS_ACTIONED
        if exc.status in (ExceptionStatus.ACKNOWLEDGED, ExceptionStatus.RESOLVED)
        else STATUS_DISMISSED
        if exc.status == ExceptionStatus.DISMISSED
        else STATUS_PENDING_REVIEW
    )
    return upsert_decision_packet_sync(
        session,
        tenant_id=tenant_id,
        packet_type=PACKET_AP_INVESTIGATION,
        entity_type=ENTITY_EXCEPTION,
        entity_id=exc.id,
        vendor_id=invoice.vendor_id,
        title=f"AP Exception: {vendor_name} · {invoice.invoice_number}",
        summary=summary,
        recommended_action=recommended_action,
        financial_impact=variance_dec,
        currency=invoice.currency or "USD",
        urgency_date=invoice.due_date.date() if invoice.due_date else invoice.invoice_date.date(),
        source_hash=source_hash,
        payload=payload,
        default_status=packet_status,
    )


def build_renewal_dossier_packet_sync(
    session: Session,
    tenant_id: str,
    contract_id: uuid.UUID,
    *,
    rag_search: Callable[..., list[dict[str, Any]]] | None = None,
) -> DecisionPacket | None:
    """Pre-compute an executive renewal dossier with live usage & RAG clauses."""
    contract = session.scalar(
        select(Contract).where(
            Contract.id == contract_id,
            Contract.tenant_id == tenant_id,
        )
    )
    if contract is None:
        return None
    vendor = session.get(Vendor, contract.vendor_id)
    vendor_name = vendor.name if vendor else "Unknown Vendor"
    ren_date = contract.renewal_date or contract.end_date
    if ren_date is None:
        return None

    notice_days = contract.notice_period_days if contract.notice_period_days is not None else 30
    notice_deadline = ren_date - timedelta(days=notice_days)
    today = datetime.now(UTC).date()
    days_to_notice = (notice_deadline - today).days

    terms_total = session.scalar(
        select(
            func.sum(
                ContractTermsVersion.unit_price
                * func.coalesce(ContractTermsVersion.qty_min, 1)
            )
        ).where(ContractTermsVersion.contract_id == contract.id)
    )
    if terms_total and float(terms_total) > 0:
        annual_spend = to_decimal(terms_total).quantize(Decimal("0.01"))
    else:
        inv_total = session.scalar(
            select(func.sum(Invoice.total_amount)).where(Invoice.contract_id == contract.id)
        )
        annual_spend = (
            (to_decimal(inv_total) * Decimal("4")).quantize(Decimal("0.01"))
            if inv_total
            else Decimal("0.00")
        )

    util = compute_vendor_utilization_sync(session, tenant_id, contract.vendor_id)
    open_exc_rows = (
        session.execute(
            select(ReconciliationException).where(
                ReconciliationException.contract_id == contract.id,
                ReconciliationException.tenant_id == tenant_id,
                ReconciliationException.status.in_(
                    [ExceptionStatus.OPEN, ExceptionStatus.ACKNOWLEDGED]
                ),
            )
        )
        .scalars()
        .all()
    )
    discrepancy_total = sum(
        (abs(to_decimal(e.variance_amount)) for e in open_exc_rows),
        Decimal("0.00"),
    )

    search_fn = rag_search or _safe_rag_search
    rag_chunks = search_fn(
        tenant_id=tenant_id,
        query=f"{vendor_name} renewal termination notice price escalation auto-renew discount",
        vendor_id=str(contract.vendor_id),
        document_type="contract",
        limit=4,
    )
    existing_doc_ids = {
        str(row_id)
        for row_id in session.execute(
            select(Document.id).where(Document.tenant_id == tenant_id)
        )
        .scalars()
        .all()
    }
    clauses: list[dict[str, Any]] = []
    for p in rag_chunks:
        doc_id = str(p.get("document_id") or "")
        if doc_id and doc_id not in existing_doc_ids:
            continue
        clauses.append(
            {
                "clause_type": str(p.get("section") or "COMMERCIAL_TERMS"),
                "summary": str(p.get("content", ""))[:160],
                "document_id": doc_id,
                "filename": p.get("filename"),
                "page": p.get("page"),
                "section": p.get("section"),
                "verbatim_excerpt": str(p.get("content", ""))[:400],
            }
        )

    leverage_points: list[str] = []
    recommended_actions: list[str] = []
    talking_points: list[str] = []
    risk_factors: list[str] = []

    if contract.auto_renew:
        if days_to_notice < 0:
            leverage_points.append(
                f"Notice deadline passed {abs(days_to_notice)}d ago ({notice_deadline.isoformat()}); request written waiver or concession."
            )
            risk_factors.append("Auto-renewal notice window has elapsed; confirm termination/renegotiation flexibility immediately.")
        else:
            leverage_points.append(
                f"Auto-renew opt-out notice due in {days_to_notice}d ({notice_deadline.isoformat()}) — preserve termination leverage."
            )
            risk_factors.append(
                f"Auto-renewal locks in on {notice_deadline.isoformat()} without written notice {notice_days}d prior."
            )
        recommended_actions.append(
            f"Record formal notice decision prior to {notice_deadline.isoformat()} ({notice_days}d notice window)."
        )
    else:
        leverage_points.append("Manual renewal agreement — zero auto-renewal lock-in risk.")

    if util["has_forecast"] and util["forecast_recommended_seats"] < util["forecast_current_seats"]:
        seat_cut = util["forecast_current_seats"] - util["forecast_recommended_seats"]
        savings_est = util["forecast_savings_estimate"]
        leverage_points.append(
            f"ML seat forecast recommends committing to {util['forecast_recommended_seats']} seats (down {seat_cut} from {util['forecast_current_seats']}) saving ~${savings_est:,.0f}/yr."
        )
        recommended_actions.append(
            f"Right-size renewal commitment from {util['forecast_current_seats']} to {util['forecast_recommended_seats']} seats."
        )
        talking_points.append(
            f"Our telemetry shows {util['idle_seats']} idle seats; we are sizing the renewal to {util['forecast_recommended_seats']} committed seats."
        )
    elif util["utilization_pct"] is not None:
        leverage_points.append(
            f"Live Okta utilization is {util['utilization_pct']}% ({util['active_users_30d']} active of {util['purchased_seats']} assigned seats)."
        )
        if util["idle_seats"] > 0:
            recommended_actions.append(
                f"Reclaim {util['idle_seats']} unused seats before signing renewal."
            )

    if discrepancy_total > Decimal("0"):
        leverage_points.append(
            f"AP Audit has {len(open_exc_rows)} open billing exception(s) totaling ${discrepancy_total:,.2f} — require credit/resolution prior to renewal."
        )
        recommended_actions.append(
            f"Tie renewal sign-off to credit resolution of ${discrepancy_total:,.2f} in open AP exceptions."
        )

    if not recommended_actions:
        recommended_actions.append(
            "Benchmark current unit pricing and request a 0% price-escalation cap on renewal."
        )
    if not talking_points:
        talking_points.append(
            f"We require flat unit pricing and flexible seat true-down terms for {contract.contract_number}."
        )
    if not risk_factors:
        risk_factors.append("Verify price-escalation caps and multi-year commitment clauses in the source agreement.")

    potential_savings = Decimal(str(util["forecast_savings_estimate"]))
    if potential_savings <= Decimal("0") and util["utilization_pct"] is not None and util["utilization_pct"] < 85.0 and annual_spend > Decimal("0"):
        unused_ratio = Decimal(str(max(0.0, 1.0 - (util["utilization_pct"] / 100.0))))
        potential_savings = (annual_spend * unused_ratio).quantize(Decimal("0.01"))

    financial_impact = (potential_savings + discrepancy_total).quantize(Decimal("0.01"))
    if financial_impact <= Decimal("0"):
        financial_impact = annual_spend

    summary_parts = [
        f"{vendor_name} ({contract.contract_number}) renews {ren_date.isoformat()}",
        f"notice {'passed' if days_to_notice < 0 else f'in {days_to_notice}d'} ({notice_deadline.isoformat()})",
    ]
    if util["utilization_pct"] is not None:
        summary_parts.append(f"{util['utilization_pct']}% seat utilization")
    if util["forecast_savings_estimate"] > 0:
        summary_parts.append(f"~${util['forecast_savings_estimate']:,.0f}/yr forecast savings")
    if discrepancy_total > 0:
        summary_parts.append(f"${discrepancy_total:,.2f} open AP exceptions")
    summary = " · ".join(summary_parts) + "."

    now_iso = datetime.now(UTC).isoformat()
    prep_payload = {
        "vendor_id": str(contract.vendor_id),
        "vendor_name": vendor_name,
        "current_annual_spend": float(annual_spend),
        "renewal_date": ren_date.isoformat(),
        "notice_period_days": notice_days,
        "auto_renewal": bool(contract.auto_renew),
        "utilization_rate": (util["utilization_pct"] / 100.0) if util["utilization_pct"] is not None else 0.0,
        "unused_licenses": util["idle_seats"],
        "potential_savings": float(potential_savings),
        "contract_constraints": risk_factors,
        "negotiation_levers": leverage_points,
        "generated_at": now_iso,
    }
    brief_payload = {
        "vendor_id": str(contract.vendor_id),
        "vendor_name": vendor_name,
        "current_spend": float(annual_spend),
        "contract_terms": {
            "contract_number": contract.contract_number,
            "auto_renew": bool(contract.auto_renew),
            "notice_period_days": notice_days,
            "termination_clause": contract.termination_clause,
        },
        "utilization_data": {
            "overall_utilization_pct": util["utilization_pct"],
            "active_users": util["active_users_30d"],
            "purchased_seats": util["purchased_seats"],
            "idle_seats": util["idle_seats"],
            "forecast_recommended_seats": util["forecast_recommended_seats"],
            "estimated_annual_savings_usd": float(potential_savings),
        },
        "leverage_points": leverage_points,
        "recommended_actions": recommended_actions,
        "talking_points": talking_points,
        "risk_factors": risk_factors,
        "contractual_clauses": clauses,
        "generated_at": now_iso,
        "cacheable": True,
    }
    source_hash = compute_source_hash(
        {
            "contract_id": str(contract.id),
            "ren_date": ren_date.isoformat(),
            "notice_days": notice_days,
            "annual_spend": str(annual_spend),
            "util": util,
            "exc_count": len(open_exc_rows),
            "discrepancy_total": str(discrepancy_total),
            "clauses": [c.get("document_id") for c in clauses],
        }
    )

    return upsert_decision_packet_sync(
        session,
        tenant_id=tenant_id,
        packet_type=PACKET_RENEWAL_DOSSIER,
        entity_type=ENTITY_CONTRACT,
        entity_id=contract.id,
        vendor_id=contract.vendor_id,
        title=f"Renewal Dossier: {vendor_name} · {contract.contract_number}",
        summary=summary,
        recommended_action=recommended_actions[0],
        financial_impact=financial_impact,
        currency="USD",
        urgency_date=notice_deadline,
        source_hash=source_hash,
        payload={
            "contract_id": str(contract.id),
            "vendor_id": str(contract.vendor_id),
            "vendor_name": vendor_name,
            "contract_number": contract.contract_number,
            "days_until_notice_deadline": days_to_notice,
            "utilization": util,
            "prep": prep_payload,
            "brief": brief_payload,
        },
    )


def build_maverick_review_packet_sync(
    session: Session,
    tenant_id: str,
    alert_id: uuid.UUID,
) -> DecisionPacket | None:
    """Pre-compute an in-app consolidation decision packet for a Maverick alert."""
    alert = session.scalar(
        select(MaverickAlert).where(
            MaverickAlert.id == alert_id,
            MaverickAlert.tenant_id == tenant_id,
        )
    )
    if alert is None:
        return None
    txn = session.get(CardTransaction, alert.transaction_id)
    if txn is None:
        return None
    emp = session.get(Employee, alert.employee_id) if alert.employee_id else None
    dept = session.get(Department, emp.department_id) if (emp and emp.department_id) else None
    contract = session.get(Contract, alert.overlap_contract_id) if alert.overlap_contract_id else None
    term = (
        session.get(ContractTermsVersion, alert.overlap_contract_term_id)
        if alert.overlap_contract_term_id
        else None
    )
    overlap_vendor = session.get(Vendor, contract.vendor_id) if contract else None

    annual_run_rate = (to_decimal(txn.amount) * Decimal("12")).quantize(Decimal("0.01"))
    emp_name = (
        f"{(emp.first_name or '').strip()} {(emp.last_name or '').strip()}".strip()
        if emp
        else (txn.cardholder_name_raw or "Employee")
    )
    dept_name = dept.name if dept else (emp.department_raw if emp and emp.department_raw else "Unassigned")
    approved_alt = (
        (term.description or term.product_code)
        if term
        else None
    )
    overlap_pct = round(float(alert.overlap_score or 0.0) * 100.0, 0)

    if approved_alt:
        summary = (
            f"{emp_name} ({dept_name}) expensed {alert.merchant_name} (${float(txn.amount):,.0f}/mo, "
            f"${annual_run_rate:,.0f}/yr) — {overlap_pct:.0f}% overlap with approved {approved_alt}"
            f"{f' ({overlap_vendor.name})' if overlap_vendor else ''}."
        )
        recommended_action = (
            f"Create consolidation task and migrate {emp_name} from {alert.merchant_name} to {approved_alt}."
        )
    else:
        summary = (
            f"{emp_name} ({dept_name}) has recurring unmanaged SaaS spend on {alert.merchant_name} "
            f"(${float(txn.amount):,.0f}/mo, ${annual_run_rate:,.0f}/yr)."
        )
        recommended_action = (
            f"Review {alert.merchant_name} subscription for consolidation or formal vendor onboarding."
        )

    source_hash = compute_source_hash(
        {
            "alert_id": str(alert.id),
            "status": alert.status.value,
            "overlap_score": str(alert.overlap_score or 0),
            "overlap_contract_id": str(alert.overlap_contract_id or ""),
            "amount": str(txn.amount),
        }
    )
    payload = {
        "alert_id": str(alert.id),
        "transaction_id": str(txn.id),
        "merchant_name": alert.merchant_name,
        "monthly_amount": float(txn.amount),
        "annual_run_rate": float(annual_run_rate),
        "employee_name": emp_name,
        "department": dept_name,
        "jev_is_saas_score": float(alert.jev_is_saas_score or 0.0),
        "jev_review_score": float(alert.jev_review_score or 0.0),
        "overlap_score": float(alert.overlap_score or 0.0),
        "approved_alternative": approved_alt,
        "approved_contract_id": str(contract.id) if contract else None,
        "approved_vendor_name": overlap_vendor.name if overlap_vendor else None,
    }
    packet_status = (
        STATUS_ACTIONED
        if alert.status == AlertStatus.MIGRATED
        else STATUS_DISMISSED
        if alert.status == AlertStatus.DISMISSED
        else STATUS_PENDING_REVIEW
    )
    return upsert_decision_packet_sync(
        session,
        tenant_id=tenant_id,
        packet_type=PACKET_MAVERICK_REVIEW,
        entity_type=ENTITY_MAVERICK_ALERT,
        entity_id=alert.id,
        vendor_id=txn.vendor_id or (contract.vendor_id if contract else None),
        title=f"Unmanaged SaaS: {alert.merchant_name} (${annual_run_rate:,.0f}/yr)",
        summary=summary,
        recommended_action=recommended_action,
        financial_impact=annual_run_rate,
        currency=txn.currency or "USD",
        urgency_date=txn.txn_date.date() if txn.txn_date else None,
        source_hash=source_hash,
        payload=payload,
        default_status=packet_status,
    )


def refresh_tenant_decision_packets_sync(
    session: Session,
    tenant_id: str,
    *,
    renewal_horizon_days: int = 90,
) -> dict[str, int]:
    """Scan active exceptions, upcoming renewals, and maverick alerts to build packets."""
    counts = {"ap_investigation": 0, "renewal_dossier": 0, "maverick_review": 0}
    today = datetime.now(UTC).date()
    max_notice_date = today + timedelta(days=renewal_horizon_days)

    exc_ids = (
        session.execute(
            select(ReconciliationException.id).where(
                ReconciliationException.tenant_id == tenant_id,
                ReconciliationException.status.in_(
                    [ExceptionStatus.OPEN, ExceptionStatus.ACKNOWLEDGED]
                ),
            )
        )
        .scalars()
        .all()
    )
    for exc_id in exc_ids:
        if build_ap_investigation_packet_sync(session, tenant_id, exc_id) is not None:
            counts["ap_investigation"] += 1

    contracts = (
        session.execute(
            select(Contract).where(
                Contract.tenant_id == tenant_id,
                Contract.status == ContractStatus.ACTIVE,
            )
        )
        .scalars()
        .all()
    )
    for contract in contracts:
        ren_date = contract.renewal_date or contract.end_date
        if ren_date is None:
            continue
        notice_days = contract.notice_period_days if contract.notice_period_days is not None else 30
        notice_deadline = ren_date - timedelta(days=notice_days)
        if notice_deadline <= max_notice_date and ren_date >= today - timedelta(days=30):
            if build_renewal_dossier_packet_sync(session, tenant_id, contract.id) is not None:
                counts["renewal_dossier"] += 1

    alert_ids = (
        session.execute(
            select(MaverickAlert.id).where(
                MaverickAlert.tenant_id == tenant_id,
                MaverickAlert.status == AlertStatus.OPEN,
            )
        )
        .scalars()
        .all()
    )
    for alert_id in alert_ids:
        if build_maverick_review_packet_sync(session, tenant_id, alert_id) is not None:
            counts["maverick_review"] += 1

    session.commit()
    logger.info("decision_packets_refreshed", tenant_id=tenant_id, **counts)
    return counts
