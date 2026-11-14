"""AP Audit & Compliance Reconciliation router."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from zellovest_procurement.api.deps import get_db_session, get_optional_user
from zellovest_procurement.schemas.compliance import (
    APAuditKPIsResponse,
    LineItemComparisonItem,
    ReconciliationExceptionItem,
    ReconciliationExceptionListResponse,
    ReconcileInvoiceResponse,
    UpdateExceptionStatusRequest,
)
from zellovest_shared.db.models import (
    Contract as ContractRow,
    ContractTermsVersion as ContractTermRow,
    ExceptionRule,
    ExceptionStatus,
    Invoice as InvoiceRow,
    InvoiceLineItem as InvoiceLineRow,
    PurchaseOrder as PurchaseOrderRow,
    ReconciliationException as ExceptionRow,
    User,
    Vendor as VendorRow,
)
from zellovest_shared.logging_conf import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/compliance", tags=["compliance"])

RULE_LABELS: dict[str, str] = {
    "price": "Price Creep",
    "quantity": "Quantity Tier Mismatch",
    "missing_po": "Missing PO",
    "discount": "Discount Omission",
    "tax": "Tax Discrepancy",
    "freight": "Freight Surcharge",
    "date": "Date Window Mismatch",
    "payment_term": "Payment Term Mismatch",
}


def _rule_explanation(
    rule_key: str,
    label: str,
    billed: float | None,
    expected: float | None,
    variance_amount: float | None,
) -> str:
    """Produce deterministic, rule-specific audit explanations."""
    b_val = billed if billed is not None else 0.0
    e_val = expected if expected is not None else 0.0
    v_val = variance_amount if variance_amount is not None else (b_val - e_val)

    if rule_key == "missing_po":
        return f"Invoice total of ${b_val:,.2f} billed without an authorized Purchase Order (Enterprise PO threshold: $5,000.00)."
    if rule_key == "freight":
        return f"Freight fee of ${b_val:,.2f} billed on FOB Destination / freight-included contract terms."
    if rule_key == "payment_term":
        return f"Payment term mismatch: invoice demands payment in {int(b_val)} days vs contracted {int(e_val)} days."
    if rule_key == "date":
        return "Invoice date falls outside the active contractual term window."
    if rule_key == "tax":
        return f"Tax billed at ${b_val:,.2f} on tax-exempt contracted schedule items."
    if rule_key == "discount":
        return f"Contractual discount omitted: billed at list price ${b_val:,.2f} vs discounted ceiling ${e_val:,.2f}."
    if rule_key == "quantity":
        return f"Billed volume of {b_val:,.0f} units falls outside contracted commitment tier ({e_val:,.0f})."
    if rule_key == "price":
        return f"Billed unit price ${b_val:,.2f} exceeds locked contractual schedule ceiling of ${e_val:,.2f}."
    return f"Variance of ${v_val:,.2f} detected under rule '{label}'."


@router.get("/kpis", response_model=APAuditKPIsResponse)
async def get_compliance_kpis(
    tenant_id: str | None = Query(default=None),
    user: User | None = Depends(get_optional_user),
    session: AsyncSession = Depends(get_db_session),
) -> APAuditKPIsResponse:
    """Return aggregated KPIs for the AP Audit & Reconciliation dashboard."""
    active_tenant = (user.tenant_id if user else None) or tenant_id or "default-org"

    # Total invoiced & count across real tenant ledger
    inv_stats = await session.execute(
        select(
            func.coalesce(func.sum(InvoiceRow.total_amount), 0),
            func.count(InvoiceRow.id),
        ).where(InvoiceRow.tenant_id == active_tenant)
    )
    total_invoiced_raw, total_invoices_raw = inv_stats.one()
    total_invoiced = float(total_invoiced_raw or 0)
    total_invoices = int(total_invoices_raw or 0)

    # Invoices that have been audited by the AP audit engine
    audited_count_stmt = select(func.count(InvoiceRow.id)).where(
        InvoiceRow.tenant_id == active_tenant,
        func.json_extract_path_text(InvoiceRow.extra, "commercial_reconciled_at").is_not(None),
    )
    audited_invoices_count = (await session.scalar(audited_count_stmt)) or 0

    # Active discrepancy amount & flagged invoice count
    exc_stats = await session.execute(
        select(
            func.coalesce(func.sum(func.abs(ExceptionRow.variance_amount)), 0),
            func.count(func.distinct(ExceptionRow.invoice_id)),
        ).where(
            ExceptionRow.tenant_id == active_tenant,
            ExceptionRow.status.in_([ExceptionStatus.OPEN, ExceptionStatus.ACKNOWLEDGED]),
        )
    )
    discrepancy_amount_raw, exception_invoices_count_raw = exc_stats.one()
    flagged_discrepancy = float(discrepancy_amount_raw or 0)
    exception_invoices_count = int(exception_invoices_count_raw or 0)

    # Clean = audited invoices with 0 open/acknowledged exceptions
    clean_invoices_count = max(0, audited_invoices_count - exception_invoices_count)
    unreconciled_invoices_count = max(0, total_invoices - audited_invoices_count)

    clean_rate = (
        round((clean_invoices_count / audited_invoices_count) * 100, 1)
        if audited_invoices_count > 0
        else 0.0
    )

    return APAuditKPIsResponse(
        total_invoiced_amount=total_invoiced,
        flagged_discrepancy_amount=flagged_discrepancy,
        total_invoices_count=total_invoices,
        clean_invoices_count=clean_invoices_count,
        exception_invoices_count=exception_invoices_count,
        unreconciled_invoices_count=unreconciled_invoices_count,
        clean_rate_pct=clean_rate,
    )


@router.get("/exceptions", response_model=ReconciliationExceptionListResponse)
async def list_reconciliation_exceptions(
    rule_type: str | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    severity: str | None = Query(default=None),
    search: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    tenant_id: str | None = Query(default=None),
    user: User | None = Depends(get_optional_user),
    session: AsyncSession = Depends(get_db_session),
) -> ReconciliationExceptionListResponse:
    """List reconciliation exceptions with filtering and pagination."""
    active_tenant = (user.tenant_id if user else None) or tenant_id or "default-org"

    query = (
        select(
            ExceptionRow,
            InvoiceRow,
            VendorRow,
            ContractRow,
            PurchaseOrderRow,
        )
        .join(InvoiceRow, InvoiceRow.id == ExceptionRow.invoice_id)
        .join(VendorRow, VendorRow.id == InvoiceRow.vendor_id)
        .outerjoin(ContractRow, ContractRow.id == ExceptionRow.contract_id)
        .outerjoin(
            PurchaseOrderRow,
            PurchaseOrderRow.id == func.coalesce(ExceptionRow.po_id, InvoiceRow.po_id),
        )
        .where(ExceptionRow.tenant_id == active_tenant)
    )

    if rule_type and rule_type.lower() != "all":
        query = query.where(ExceptionRow.rule_type == rule_type)

    if status_filter and status_filter.lower() != "all":
        query = query.where(ExceptionRow.status == status_filter)
    elif not status_filter:
        # Default to active exceptions requiring action
        query = query.where(
            ExceptionRow.status.in_([ExceptionStatus.OPEN, ExceptionStatus.ACKNOWLEDGED])
        )

    if severity and severity.lower() != "all":
        query = query.where(ExceptionRow.severity == severity)

    if search and search.strip():
        search_pattern = f"%{search.strip().lower()}%"
        query = query.where(
            or_(
                func.lower(InvoiceRow.invoice_number).like(search_pattern),
                func.lower(VendorRow.name).like(search_pattern),
                func.lower(ContractRow.contract_number).like(search_pattern),
            )
        )

    # Count total
    count_stmt = select(func.count()).select_from(query.subquery())
    total_count = (await session.execute(count_stmt)).scalar_one()

    # Paginate
    query = query.order_by(ExceptionRow.detected_at.desc())
    query = query.offset((page - 1) * page_size).limit(page_size)
    rows = (await session.execute(query)).all()

    items: list[ReconciliationExceptionItem] = []
    for exc, inv, vendor, contract, po in rows:
        rule_key = exc.rule_type.value if hasattr(exc.rule_type, "value") else str(exc.rule_type)
        label = RULE_LABELS.get(rule_key, rule_key.replace("_", " ").title())

        # Load linked or fallback comparison line items
        line_items_comparison: list[LineItemComparisonItem] = []
        inv_line = (
            await session.get(InvoiceLineRow, exc.invoice_line_id)
            if exc.invoice_line_id
            else None
        )
        contract_term = (
            await session.get(ContractTermRow, exc.contract_term_id)
            if exc.contract_term_id
            else None
        )

        reason = _rule_explanation(
            rule_key=rule_key,
            label=label,
            billed=exc.billed_value,
            expected=exc.expected_value,
            variance_amount=exc.variance_amount,
        )

        if inv_line:
            # Concrete billed line item exists
            contracted_price = (
                float(exc.expected_value)
                if exc.expected_value is not None
                else float(contract_term.unit_price if contract_term else 0.0)
            )
            billed_price = (
                float(exc.billed_value)
                if exc.billed_value is not None
                else float(inv_line.unit_price)
            )
            unit_variance = round(billed_price - contracted_price, 2)
            extended_var = float(exc.variance_amount) if exc.variance_amount is not None else round(unit_variance * float(inv_line.quantity), 2)

            line_items_comparison.append(
                LineItemComparisonItem(
                    id=str(inv_line.id),
                    line_number=inv_line.line_no,
                    product_code=inv_line.product_code or (contract_term.product_code if contract_term else None),
                    description=inv_line.description or (contract_term.description if contract_term else "Line item discrepancy"),
                    billed_unit_price=billed_price,
                    contracted_unit_price=contracted_price,
                    billed_quantity=float(inv_line.quantity),
                    tier_min_quantity=float(contract_term.qty_min) if (contract_term and contract_term.qty_min) else None,
                    tier_max_quantity=float(contract_term.qty_max) if (contract_term and contract_term.qty_max) else None,
                    variance_amount=unit_variance,
                    extended_variance_amount=extended_var,
                    variance_pct=exc.variance_pct,
                    rule=rule_key,
                    explanation=reason,
                )
            )
        else:
            # Header-level discrepancy: synthesize row from exception totals
            billed_val = float(exc.billed_value or 0.0)
            expected_val = float(exc.expected_value or 0.0)
            extended_var = float(exc.variance_amount or 0.0)

            line_items_comparison.append(
                LineItemComparisonItem(
                    id=f"syn-{exc.id}",
                    line_number=1,
                    product_code=contract_term.product_code if contract_term else f"{rule_key.upper()}-RULE",
                    description=contract_term.description if contract_term else f"{label} (Invoice Header)",
                    billed_unit_price=billed_val,
                    contracted_unit_price=expected_val,
                    billed_quantity=1.0,
                    tier_min_quantity=float(contract_term.qty_min) if (contract_term and contract_term.qty_min) else None,
                    tier_max_quantity=float(contract_term.qty_max) if (contract_term and contract_term.qty_max) else None,
                    variance_amount=round(billed_val - expected_val, 2),
                    extended_variance_amount=extended_var,
                    variance_pct=exc.variance_pct,
                    rule=rule_key,
                    explanation=reason,
                )
            )

        items.append(
            ReconciliationExceptionItem(
                id=exc.id,
                invoice_id=inv.id,
                invoice_number=inv.invoice_number,
                vendor_id=vendor.id,
                vendor_name=vendor.name,
                invoice_date=inv.invoice_date.date().isoformat(),
                due_date=inv.due_date.date().isoformat() if inv.due_date else None,
                total_amount=float(inv.total_amount),
                currency=inv.currency,
                discrepancy_amount=float(exc.variance_amount or 0),
                primary_rule=rule_key,
                rule_label=label,
                severity=exc.severity,
                status=exc.status.value if hasattr(exc.status, "value") else str(exc.status),
                contract_id=contract.id if contract else exc.contract_id,
                contract_number=contract.contract_number if contract else "MSA-UNKNOWN",
                contract_title=contract.title if contract else "Master Agreement",
                po_number=po.po_number if po else None,
                detected_at=exc.detected_at,
                investigation_reason=reason,
                line_items_comparison=line_items_comparison,
            )
        )

    return ReconciliationExceptionListResponse(
        items=items,
        total=total_count,
        page=page,
        page_size=page_size,
    )


@router.patch("/exceptions/{exception_id}/status", response_model=dict)
async def update_exception_status(
    exception_id: UUID,
    body: UpdateExceptionStatusRequest,
    user: User | None = Depends(get_optional_user),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """Update exception status (e.g. acknowledged, resolved, or dismissed)."""
    active_tenant = user.tenant_id if user else "default-org"
    exc = await session.execute(
        select(ExceptionRow)
        .where(
            ExceptionRow.id == exception_id,
            ExceptionRow.tenant_id == active_tenant,
        )
        .with_for_update()
    )
    exception_record = exc.scalar_one_or_none()
    if exception_record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Exception not found.")

    valid_statuses = {"open", "acknowledged", "resolved", "dismissed"}
    if body.status not in valid_statuses:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid status '{body.status}'. Expected one of: {sorted(valid_statuses)}.",
        )

    exception_record.status = ExceptionStatus(body.status)
    if body.status in {"resolved", "dismissed"}:
        exception_record.resolved_at = datetime.now(UTC)
    else:
        exception_record.resolved_at = None

    # Check if all exceptions on this invoice are resolved/dismissed for active_tenant
    remaining_open = (
        await session.scalar(
            select(func.count(ExceptionRow.id)).where(
                ExceptionRow.invoice_id == exception_record.invoice_id,
                ExceptionRow.tenant_id == active_tenant,
                ExceptionRow.status.in_([ExceptionStatus.OPEN, ExceptionStatus.ACKNOWLEDGED]),
            )
        )
        or 0
    )
    if remaining_open == 0:
        inv = await session.get(InvoiceRow, exception_record.invoice_id)
        if inv:
            inv.status = "approved"

    await session.commit()
    logger.info("exception_status_updated", exception_id=str(exception_id), new_status=body.status)
    return {"status": "ok", "exception_id": str(exception_id), "new_status": body.status}


@router.post("/invoices/{invoice_id}/reconcile", response_model=ReconcileInvoiceResponse)
async def trigger_invoice_reconcile(
    invoice_id: UUID,
    force: bool = Query(default=True),
    user: User | None = Depends(get_optional_user),
    session: AsyncSession = Depends(get_db_session),
) -> ReconcileInvoiceResponse:
    """Manually trigger or re-run deterministic AP audit on an invoice."""
    inv = await session.get(InvoiceRow, invoice_id)
    active_tenant = (user.tenant_id if user else None) or (inv.tenant_id if inv else "default-org")
    if inv is None or inv.tenant_id != active_tenant:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invoice not found.")

    try:
        from zellovest_workers.tasks.ap_audit import reconcile_invoice

        res = reconcile_invoice(active_tenant, str(invoice_id), force=force)
        return ReconcileInvoiceResponse(
            tenant_id=active_tenant,
            invoice_id=str(invoice_id),
            status=res.get("status", "completed"),
            contract_id=res.get("contract_id"),
            exception_count=res.get("exception_count", 0),
            total_discrepancy_amount=res.get("total_discrepancy_amount", 0.0),
        )
    except Exception as exc:
        logger.error(
            "reconcile_invocation_failed",
            invoice_id=str(invoice_id),
            error=str(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Reconciliation failed: {exc}",
        ) from exc
