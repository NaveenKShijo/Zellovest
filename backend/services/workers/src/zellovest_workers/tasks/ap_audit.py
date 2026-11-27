"""Deterministic invoice-to-contract reconciliation engine.

Performs point-in-time commercial term compliance checks comparing invoice
line items and headers against versioned contract schedules in PostgreSQL.
Financial math is strictly deterministic using Python Decimal (zero LLM math).
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from zellovest_shared.db.models import (
    Contract as ContractRow,
    ContractTermsVersion as ContractTermRow,
    ContractVersion as ContractVersionRow,
    Document as DocumentRow,
    ExceptionRule,
    ExceptionStatus,
    ExtractionArtifact,
    Invoice as InvoiceRow,
    InvoiceLineItem as InvoiceLineRow,
    PurchaseOrder as PurchaseOrderRow,
    ReconciliationException,
)
from zellovest_shared.db.session import get_sync_engine
from zellovest_shared.logging_conf import get_logger
from zellovest_workers.celery_app import QUEUE_ANALYTICS, celery_app

logger = get_logger(__name__)

_PRICE_TOLERANCE = Decimal("0.01")
_NET_DAYS = re.compile(r"\bnet\s+(\d{1,3})\b", re.IGNORECASE)
_PERCENT_RATE = re.compile(r"(\d+(?:\.\d+)?)\s*%")
_FREIGHT_KEYWORDS = (
    "freight",
    "shipping",
    "delivery",
    "postage",
    "carrier",
    "handling fee",
    "transportation",
)
_FREIGHT_INCLUDED_TERMS = (
    "fob destination",
    "included",
    "prepaid",
    "free shipping",
    "zero",
    "exempt",
    "no charge",
)


def compare_line_item(contract_price: Decimal, invoice_price: Decimal) -> dict[str, Any]:
    """Return deterministic unit-price variance values for one invoice line."""
    if contract_price == 0:
        return {
            "contract_price": str(contract_price),
            "invoice_price": str(invoice_price),
            "variance_pct": None,
            "exception": invoice_price != contract_price,
        }
    variance = (invoice_price - contract_price) / contract_price * Decimal("100")
    return {
        "contract_price": str(contract_price),
        "invoice_price": str(invoice_price),
        "variance_pct": float(variance),
        "exception": abs(invoice_price - contract_price) > _PRICE_TOLERANCE,
    }


def _decimal(value: Any) -> Decimal:
    """Convert a database or wire numeric value to Decimal without float math."""
    return Decimal(str(value or 0))


def _text(value: str | None) -> str:
    """Normalize product identifiers and descriptions for exact comparisons."""
    return " ".join((value or "").split()).casefold()


def _same_product(invoice_line: InvoiceLineRow, term: ContractTermRow) -> bool:
    """Match an invoice line to a contract line by product code or description."""
    invoice_code = _text(invoice_line.product_code)
    term_code = _text(term.product_code)
    if invoice_code and term_code:
        return invoice_code == term_code
    return bool(_text(invoice_line.description)) and _text(invoice_line.description) == _text(
        term.description
    )


def _within_quantity(term: ContractTermRow, quantity: Decimal) -> bool:
    """Check the term's optional minimum and maximum quantity limits."""
    minimum = _decimal(term.qty_min) if term.qty_min is not None else None
    maximum = _decimal(term.qty_max) if term.qty_max is not None else None
    return (minimum is None or quantity >= minimum) and (
        maximum is None or quantity <= maximum
    )


def _payment_days(value: str | None) -> int | None:
    """Extract a simple Net N payment period when the invoice has a due date."""
    match = _NET_DAYS.search(value or "")
    return int(match.group(1)) if match else None


def _tax_rate(value: str | None) -> Decimal | None:
    """Parse an explicit percentage or recognized exempt rule as a fraction."""
    normalized = _text(value).replace("-", " ")
    if "exempt" in normalized or "zero rated" in normalized or "tax free" in normalized:
        return Decimal("0")
    matches = _PERCENT_RATE.findall(value or "")
    if len(matches) != 1:
        return None
    rate = Decimal(matches[0]) / Decimal("100")
    return rate if Decimal("0") <= rate <= Decimal("1") else None


def _compute_escalated_price(
    base_price: Decimal,
    escalation_pct: Decimal | None,
    start_date: date,
    invoice_date: date,
) -> Decimal:
    """Calculate annual escalation cap ceiling using exact Decimal math.

    Permits compounding at escalation_pct per elapsed 365-day contract year.
    """
    if not escalation_pct or escalation_pct <= Decimal("0"):
        return base_price
    days_elapsed = (invoice_date - start_date).days
    years_elapsed = max(0, days_elapsed // 365)
    if years_elapsed == 0:
        return base_price
    # base_price * (1 + escalation_pct/100) ^ years_elapsed
    multiplier = (Decimal("1") + (escalation_pct / Decimal("100"))) ** years_elapsed
    return (base_price * multiplier).quantize(Decimal("0.01"))


def _is_freight_line(line: InvoiceLineRow) -> bool:
    """Detect if an invoice line is a freight or delivery charge."""
    desc = _text(line.description)
    code = _text(line.product_code)
    return any(kw in desc or kw in code for kw in _FREIGHT_KEYWORDS)


def _is_freight_included(freight_terms: str | None) -> bool:
    """Check if contractual terms state that freight is included/FOB Destination."""
    norm = _text(freight_terms)
    return any(kw in norm for kw in _FREIGHT_INCLUDED_TERMS)


def _review_invoice(
    session: Session,
    *,
    invoice: InvoiceRow,
    document: DocumentRow | None,
    artifact: ExtractionArtifact | None,
    reason: str,
) -> dict[str, Any]:
    """Mark the invoice for human attention when a unique term cannot be found."""
    metadata = dict(invoice.extra or {})
    metadata["commercial_review_reason"] = reason
    metadata["commercial_reconciled_at"] = datetime.now(UTC).isoformat()
    invoice.extra = metadata
    if document is not None:
        document.status = "review_needed"
    if artifact is not None:
        review_data = dict(artifact.review_data or {})
        review_data.update(
            {
                "status": "pending",
                "document_type": "invoice",
                "reason": reason,
                "commercial_match_required": True,
            }
        )
        if artifact.review_status != "committed":
            artifact.review_status = "pending"
        artifact.review_data = review_data
    session.commit()
    logger.warning(
        "invoice_contract_match_review_required",
        tenant_id=invoice.tenant_id,
        invoice_id=str(invoice.id),
        reason=reason,
    )
    return {
        "tenant_id": invoice.tenant_id,
        "invoice_id": str(invoice.id),
        "status": "review_needed",
        "reason": reason,
    }


def _make_exception(
    *,
    invoice: InvoiceRow,
    invoice_line: InvoiceLineRow | None,
    contract: ContractRow,
    version: ContractVersionRow,
    term: ContractTermRow,
    rule: ExceptionRule,
    expected: Decimal | None,
    billed: Decimal | None,
    variance_amount: Decimal | None = None,
    variance_pct: float | None = None,
    po_id: UUID | None = None,
    severity_override: str | None = None,
) -> ReconciliationException:
    """Build an immutable exception tied to its exact contract version and term."""
    if severity_override:
        severity = severity_override
    else:
        magnitude = abs(variance_pct or 0)
        severity = "high" if magnitude >= 10 else "medium" if magnitude >= 2 else "low"
    return ReconciliationException(
        tenant_id=invoice.tenant_id,
        invoice_id=invoice.id,
        invoice_line_id=invoice_line.id if invoice_line else None,
        contract_id=contract.id,
        contract_version_id=version.id,
        contract_term_id=term.id,
        po_id=po_id or invoice.po_id,
        rule_type=rule,
        expected_value=float(expected) if expected is not None else None,
        billed_value=float(billed) if billed is not None else None,
        variance_amount=float(variance_amount) if variance_amount is not None else None,
        variance_pct=variance_pct,
        severity=severity,
        status=ExceptionStatus.OPEN,
    )


@celery_app.task(
    name="zellovest.workers.tasks.ap_audit.reconcile_invoice",
    queue=QUEUE_ANALYTICS,
    max_retries=3,
)
def reconcile_invoice(
    tenant_id: str,
    invoice_id: str,
    force: bool = False,
) -> dict[str, Any]:
    """Compare invoice lines and header with effective vendor contract terms."""
    logger.info("reconcile_started", tenant_id=tenant_id, invoice_id=invoice_id, force=force)
    engine = get_sync_engine()
    with Session(engine) as session:
        invoice = session.execute(
            select(InvoiceRow)
            .where(
                InvoiceRow.id == UUID(invoice_id),
                InvoiceRow.tenant_id == tenant_id,
            )
            .with_for_update()
        ).scalar_one_or_none()
        if invoice is None:
            logger.warning("reconcile_invoice_not_found", tenant_id=tenant_id, invoice_id=invoice_id)
            return {"tenant_id": tenant_id, "invoice_id": invoice_id, "status": "not_found"}

        metadata = dict(invoice.extra or {})
        if metadata.get("commercial_reconciled_at") and not force:
            logger.info("reconcile_invoice_idempotent", tenant_id=tenant_id, invoice_id=invoice_id)
            return {
                "tenant_id": tenant_id,
                "invoice_id": invoice_id,
                "status": "already_reconciled",
            }

        # Clear existing exceptions on force re-reconciliation
        if force:
            old_exc_ids = session.execute(
                select(ReconciliationException.id).where(
                    ReconciliationException.tenant_id == tenant_id,
                    ReconciliationException.invoice_id == invoice.id,
                )
            ).scalars().all()
            if old_exc_ids:
                from zellovest_shared.db.intelligence import DecisionPacket

                session.execute(
                    delete(DecisionPacket).where(
                        DecisionPacket.tenant_id == tenant_id,
                        DecisionPacket.entity_type == "reconciliation_exception",
                        DecisionPacket.entity_id.in_(old_exc_ids),
                    )
                )
            session.execute(
                delete(ReconciliationException).where(
                    ReconciliationException.tenant_id == tenant_id,
                    ReconciliationException.invoice_id == invoice.id,
                )
            )

        if invoice.vendor_id is None:
            document = session.get(DocumentRow, invoice.document_id) if invoice.document_id else None
            artifact = (
                session.execute(
                    select(ExtractionArtifact).where(
                        ExtractionArtifact.upload_id == document.upload_id
                    )
                ).scalar_one_or_none()
                if document is not None and document.upload_id is not None
                else None
            )
            return _review_invoice(
                session,
                invoice=invoice,
                document=document,
                artifact=artifact,
                reason="A canonical vendor could not be resolved for this invoice.",
            )

        invoice_date = invoice.invoice_date.date()
        lines = session.execute(
            select(InvoiceLineRow)
            .where(
                InvoiceLineRow.invoice_id == invoice.id,
                InvoiceLineRow.tenant_id == tenant_id,
            )
            .order_by(InvoiceLineRow.line_no)
        ).scalars().all()
        if not lines:
            document = session.get(DocumentRow, invoice.document_id) if invoice.document_id else None
            artifact = (
                session.execute(
                    select(ExtractionArtifact).where(
                        ExtractionArtifact.upload_id == document.upload_id
                    )
                ).scalar_one_or_none()
                if document is not None and document.upload_id is not None
                else None
            )
            return _review_invoice(
                session,
                invoice=invoice,
                document=document,
                artifact=artifact,
                reason="Invoice has no line items to match against commercial terms.",
            )

        # Query all contracts and versioned terms for this vendor
        joined = session.execute(
            select(ContractTermRow, ContractVersionRow, ContractRow)
            .join(
                ContractVersionRow,
                ContractVersionRow.id == ContractTermRow.contract_version_id,
            )
            .join(ContractRow, ContractRow.id == ContractTermRow.contract_id)
            .where(
                ContractTermRow.tenant_id == tenant_id,
                ContractRow.tenant_id == tenant_id,
                ContractRow.vendor_id == invoice.vendor_id,
            )
        ).all()

        vendor_contracts = session.execute(
            select(ContractRow).where(
                ContractRow.tenant_id == tenant_id,
                ContractRow.vendor_id == invoice.vendor_id,
            )
        ).scalars().all()

        if not vendor_contracts or not joined:
            document = session.get(DocumentRow, invoice.document_id) if invoice.document_id else None
            artifact = (
                session.execute(
                    select(ExtractionArtifact).where(
                        ExtractionArtifact.upload_id == document.upload_id
                    )
                ).scalar_one_or_none()
                if document is not None and document.upload_id is not None
                else None
            )
            return _review_invoice(
                session,
                invoice=invoice,
                document=document,
                artifact=artifact,
                reason="No active commercial contract found in the ledger for this vendor.",
            )

        exceptions: list[ReconciliationException] = []
        matched_contract_ids: set[UUID] = set()
        matched_terms: list[tuple[InvoiceLineRow, ContractRow, ContractVersionRow, ContractTermRow]] = []
        review_reason: str | None = None

        # ---------------------------------------------------------------------
        # Rule 8: Premature and Post-Expiration Date Boundaries
        # ---------------------------------------------------------------------
        all_starts = [t.effective_from for t, _, _ in joined if t.effective_from is not None] or [
            c.start_date for c in vendor_contracts if c.start_date is not None
        ]
        earliest_start = min(all_starts) if all_starts else None

        has_open_ended = any(t.effective_to is None for t, _, _ in joined) or any(
            c.end_date is None for c in vendor_contracts
        )
        all_ends = [t.effective_to for t, _, _ in joined if t.effective_to is not None] or [
            c.end_date for c in vendor_contracts if c.end_date is not None
        ]
        latest_end = max(all_ends) if (all_ends and not has_open_ended) else None

        # Premature billing check
        if earliest_start and invoice_date < earliest_start:
            default_term, default_version, default_contract = joined[0]
            exceptions.append(
                _make_exception(
                    invoice=invoice,
                    invoice_line=lines[0] if lines else None,
                    contract=default_contract,
                    version=default_version,
                    term=default_term,
                    rule=ExceptionRule.DATE,
                    expected=Decimal("0.00"),
                    billed=_decimal(invoice.total_amount),
                    variance_amount=_decimal(invoice.total_amount),
                    variance_pct=100.0,
                    severity_override="high",
                )
            )

        # Post-expiration billing check
        if latest_end and invoice_date > latest_end:
            default_term, default_version, default_contract = joined[0]
            exceptions.append(
                _make_exception(
                    invoice=invoice,
                    invoice_line=lines[0] if lines else None,
                    contract=default_contract,
                    version=default_version,
                    term=default_term,
                    rule=ExceptionRule.DATE,
                    expected=Decimal("0.00"),
                    billed=_decimal(invoice.total_amount),
                    variance_amount=_decimal(invoice.total_amount),
                    variance_pct=100.0,
                    severity_override="high",
                )
            )

        # ---------------------------------------------------------------------
        # Rule 9: Purchase Order Linkage & Ceiling Check
        # ---------------------------------------------------------------------
        po_row: PurchaseOrderRow | None = None
        if invoice.po_id is not None:
            po_row = session.get(PurchaseOrderRow, invoice.po_id)
            if po_row is not None:
                if po_row.vendor_id != invoice.vendor_id:
                    default_term, default_version, default_contract = joined[0]
                    exceptions.append(
                        _make_exception(
                            invoice=invoice,
                            invoice_line=lines[0] if lines else None,
                            contract=default_contract,
                            version=default_version,
                            term=default_term,
                            rule=ExceptionRule.MISSING_PO,
                            expected=Decimal("0.00"),
                            billed=_decimal(invoice.total_amount),
                            variance_amount=_decimal(invoice.total_amount),
                            variance_pct=100.0,
                            po_id=po_row.id,
                            severity_override="high",
                        )
                    )
                elif _decimal(invoice.total_amount) > _decimal(po_row.total_amount) + _PRICE_TOLERANCE:
                    default_term, default_version, default_contract = joined[0]
                    po_variance = _decimal(invoice.total_amount) - _decimal(po_row.total_amount)
                    po_pct = (
                        float((po_variance / _decimal(po_row.total_amount)) * Decimal("100"))
                        if po_row.total_amount
                        else 100.0
                    )
                    exceptions.append(
                        _make_exception(
                            invoice=invoice,
                            invoice_line=lines[0] if lines else None,
                            contract=default_contract,
                            version=default_version,
                            term=default_term,
                            rule=ExceptionRule.MISSING_PO,
                            expected=_decimal(po_row.total_amount),
                            billed=_decimal(invoice.total_amount),
                            variance_amount=po_variance,
                            variance_pct=po_pct,
                            po_id=po_row.id,
                            severity_override="high" if po_pct >= 10 else "medium",
                        )
                    )
        elif _decimal(invoice.total_amount) >= Decimal("5000.00"):
            # Standard enterprise threshold requiring an authorized purchase order
            default_term, default_version, default_contract = joined[0]
            exceptions.append(
                _make_exception(
                    invoice=invoice,
                    invoice_line=lines[0] if lines else None,
                    contract=default_contract,
                    version=default_version,
                    term=default_term,
                    rule=ExceptionRule.MISSING_PO,
                    expected=Decimal("0.00"),
                    billed=_decimal(invoice.total_amount),
                    variance_amount=_decimal(invoice.total_amount),
                    variance_pct=100.0,
                    severity_override="high" if _decimal(invoice.total_amount) >= Decimal("25000") else "medium",
                )
            )

        # ---------------------------------------------------------------------
        # Rules 1-4, 7: Line Item Rate, Escalation, Quantity & Freight Checks
        # ---------------------------------------------------------------------
        for invoice_line in lines:
            # Check for freight lines against contract freight terms
            if _is_freight_line(invoice_line):
                # Search if contract provides freight included / FOB Destination
                freight_terms_list = [term.freight_terms for term, _, _ in joined if term.freight_terms]
                if any(_is_freight_included(f) for f in freight_terms_list):
                    billed_freight = _decimal(invoice_line.total)
                    if billed_freight > _PRICE_TOLERANCE:
                        default_term, default_version, default_contract = joined[0]
                        exceptions.append(
                            _make_exception(
                                invoice=invoice,
                                invoice_line=invoice_line,
                                contract=default_contract,
                                version=default_version,
                                term=default_term,
                                rule=ExceptionRule.FREIGHT,
                                expected=Decimal("0.00"),
                                billed=billed_freight,
                                variance_amount=billed_freight,
                                variance_pct=100.0,
                                severity_override="medium",
                            )
                        )
                        continue

            product_rows = [
                (term, version, contract)
                for term, version, contract in joined
                if _same_product(invoice_line, term)
            ]
            active_rows = [
                (term, version, contract)
                for term, version, contract in product_rows
                if term.effective_from <= invoice_date
                and (term.effective_to is None or term.effective_to >= invoice_date)
            ]
            if not active_rows:
                # Check if product was active in past or future (Date window mismatch)
                if product_rows:
                    past_or_future_term, version, contract = product_rows[0]
                    exceptions.append(
                        _make_exception(
                            invoice=invoice,
                            invoice_line=invoice_line,
                            contract=contract,
                            version=version,
                            term=past_or_future_term,
                            rule=ExceptionRule.DATE,
                            expected=Decimal("0.00"),
                            billed=_decimal(invoice_line.total),
                            variance_amount=_decimal(invoice_line.total),
                            variance_pct=100.0,
                            severity_override="high",
                        )
                    )
                    continue

                review_reason = (
                    f"No effective contract term matches invoice line {invoice_line.line_no} "
                    f"on {invoice_date.isoformat()}."
                )
                break

            currency_terms = {term.currency.upper() for term, _, _ in active_rows}
            if len(currency_terms) != 1 or invoice.currency.upper() not in currency_terms:
                expected_currencies = ", ".join(sorted(currency_terms))
                review_reason = (
                    f"Invoice currency {invoice.currency} does not match contract currency "
                    f"{expected_currencies} on line {invoice_line.line_no}."
                )
                break

            quantity = _decimal(invoice_line.quantity)
            in_range = [
                row for row in active_rows if _within_quantity(row[0], quantity)
            ]
            if len(in_range) == 1:
                term, version, contract = in_range[0]
            elif len(in_range) == 0 and len(active_rows) == 1:
                term, version, contract = active_rows[0]
                matched_terms.append((invoice_line, contract, version, term))
                expected_quantity = (
                    _decimal(term.qty_min)
                    if term.qty_min is not None and quantity < _decimal(term.qty_min)
                    else _decimal(term.qty_max)
                    if term.qty_max is not None and quantity > _decimal(term.qty_max)
                    else None
                )
                exceptions.append(
                    _make_exception(
                        invoice=invoice,
                        invoice_line=invoice_line,
                        contract=contract,
                        version=version,
                        term=term,
                        rule=ExceptionRule.QUANTITY,
                        expected=expected_quantity,
                        billed=quantity,
                        variance_amount=(
                            quantity - expected_quantity
                            if expected_quantity is not None
                            else None
                        ),
                    )
                )
                matched_contract_ids.add(contract.id)
                continue
            else:
                review_reason = (
                    f"Invoice line {invoice_line.line_no} matches multiple contract quantity tiers; "
                    "a reviewer must select the applicable term."
                )
                break

            matched_terms.append((invoice_line, contract, version, term))

            # Base Price & Annual Escalation Cap
            contract_start = (
                version.contract_start_date
                or contract.start_date
                or term.effective_from
            )
            escalation_pct = _decimal(term.escalation_pct) if term.escalation_pct is not None else None
            base_price = _compute_escalated_price(
                _decimal(term.unit_price),
                escalation_pct,
                contract_start,
                invoice_date,
            )

            # Contractual Discount
            discount_pct = _decimal(term.discount_pct) if term.discount_pct is not None else Decimal("0")
            expected_price = base_price * (Decimal("100") - discount_pct) / Decimal("100")
            billed_price = _decimal(invoice_line.unit_price)

            comparison = compare_line_item(expected_price, billed_price)
            if comparison["exception"]:
                rule = (
                    ExceptionRule.DISCOUNT
                    if discount_pct and abs(billed_price - base_price) <= _PRICE_TOLERANCE
                    else ExceptionRule.PRICE
                )
                variance = billed_price - expected_price
                exceptions.append(
                    _make_exception(
                        invoice=invoice,
                        invoice_line=invoice_line,
                        contract=contract,
                        version=version,
                        term=term,
                        rule=rule,
                        expected=expected_price,
                        billed=billed_price,
                        variance_amount=variance * quantity,
                        variance_pct=comparison["variance_pct"],
                    )
                )
            matched_contract_ids.add(contract.id)

        document = session.get(DocumentRow, invoice.document_id) if invoice.document_id else None
        artifact = (
            session.execute(
                select(ExtractionArtifact).where(
                    ExtractionArtifact.upload_id == document.upload_id
                )
            ).scalar_one_or_none()
            if document is not None and document.upload_id is not None
            else None
        )
        if review_reason is not None:
            return _review_invoice(
                session,
                invoice=invoice,
                document=document,
                artifact=artifact,
                reason=review_reason,
            )

        # ---------------------------------------------------------------------
        # Rule 6: Payment Terms & Net Days Verification
        # ---------------------------------------------------------------------
        if invoice.due_date is not None and matched_terms:
            payment_periods = [
                _payment_days(term.payment_terms)
                for _, _, _, term in matched_terms
                if term.payment_terms
            ]
            known_payment_periods = {days for days in payment_periods if days is not None}
            if known_payment_periods and any(days is None for days in payment_periods):
                return _review_invoice(
                    session,
                    invoice=invoice,
                    document=document,
                    artifact=artifact,
                    reason="Matched contract lines use payment terms that cannot be compared consistently.",
                )
            payment_periods = list(known_payment_periods)
            if len(payment_periods) > 1:
                return _review_invoice(
                    session,
                    invoice=invoice,
                    document=document,
                    artifact=artifact,
                    reason="Matched contract lines specify different Net payment periods for one invoice.",
                )
            if payment_periods:
                expected_days = next(iter(payment_periods))
                billed_days = (invoice.due_date.date() - invoice_date).days
                if billed_days != expected_days:
                    line, contract, version, term = matched_terms[0]
                    exceptions.append(
                        _make_exception(
                            invoice=invoice,
                            invoice_line=line,
                            contract=contract,
                            version=version,
                            term=term,
                            rule=ExceptionRule.PAYMENT_TERM,
                            expected=Decimal(expected_days),
                            billed=Decimal(billed_days),
                            variance_amount=Decimal(billed_days - expected_days),
                        )
                    )

        # ---------------------------------------------------------------------
        # Rule 5: Tax Exemption & Rate Verification
        # ---------------------------------------------------------------------
        if matched_terms:
            tax_rates = [_tax_rate(term.tax_rule) for _, _, _, term in matched_terms]
            if all(rate is not None for rate in tax_rates):
                expected_tax = sum(
                    (
                        _decimal(line.total) * rate
                        for (line, _, _, _), rate in zip(matched_terms, tax_rates, strict=True)
                        if rate is not None
                    ),
                    Decimal("0"),
                )
                billed_tax = _decimal(invoice.tax_amount)
                if abs(expected_tax - billed_tax) > _PRICE_TOLERANCE:
                    line, contract, version, term = matched_terms[0]
                    tax_variance_pct = (
                        float((billed_tax - expected_tax) / expected_tax * Decimal("100"))
                        if expected_tax != 0
                        else 100.0
                    )
                    exceptions.append(
                        _make_exception(
                            invoice=invoice,
                            invoice_line=line,
                            contract=contract,
                            version=version,
                            term=term,
                            rule=ExceptionRule.TAX,
                            expected=expected_tax,
                            billed=billed_tax,
                            variance_amount=billed_tax - expected_tax,
                            variance_pct=tax_variance_pct,
                        )
                    )

        if len(matched_contract_ids) == 1:
            invoice.contract_id = next(iter(matched_contract_ids))
        for exception in exceptions:
            session.add(exception)

        # Update invoice status and metadata
        invoice.status = "flagged" if exceptions else "matched"
        total_discrepancy = sum(abs(e.variance_amount or 0) for e in exceptions)
        metadata["commercial_reconciled_at"] = datetime.now(UTC).isoformat()
        metadata["commercial_exception_count"] = len(exceptions)
        metadata["total_discrepancy_amount"] = float(total_discrepancy)
        invoice.extra = metadata
        session.commit()

        if exceptions:
            try:
                from zellovest_workers.tasks.decision_packets import (
                    precompute_ap_investigation_packet,
                )

                for exc_row in exceptions:
                    precompute_ap_investigation_packet.delay(
                        tenant_id=tenant_id,
                        exception_id=str(exc_row.id),
                    )
            except Exception as pkt_exc:
                logger.warning(
                    "ap_investigation_packet_enqueue_failed",
                    tenant_id=tenant_id,
                    invoice_id=invoice_id,
                    error_class=type(pkt_exc).__name__,
                )

        logger.info(
            "reconcile_completed",
            tenant_id=tenant_id,
            invoice_id=invoice_id,
            contract_id=str(invoice.contract_id) if invoice.contract_id else None,
            exception_count=len(exceptions),
            total_discrepancy=float(total_discrepancy),
        )
        return {
            "tenant_id": tenant_id,
            "invoice_id": invoice_id,
            "status": "flagged" if exceptions else "matched",
            "contract_id": str(invoice.contract_id) if invoice.contract_id else None,
            "exception_count": len(exceptions),
            "total_discrepancy_amount": float(total_discrepancy),
        }


@celery_app.task(name="zellovest.workers.tasks.ap_audit.reconcile_vendor", queue=QUEUE_ANALYTICS)
def reconcile_vendor(tenant_id: str, vendor_id: str) -> dict[str, Any]:
    """Queue reconciliation for invoices that have not yet been audited."""
    logger.info("reconcile_vendor_started", tenant_id=tenant_id, vendor_id=vendor_id)
    engine = get_sync_engine()
    with Session(engine) as session:
        invoice_ids = session.execute(
            select(InvoiceRow.id).where(
                InvoiceRow.tenant_id == tenant_id,
                InvoiceRow.vendor_id == UUID(vendor_id),
            )
        ).scalars().all()
    for current_invoice_id in invoice_ids:
        reconcile_invoice.delay(tenant_id, str(current_invoice_id))
    return {
        "tenant_id": tenant_id,
        "vendor_id": vendor_id,
        "status": "queued",
        "invoice_count": len(invoice_ids),
    }
