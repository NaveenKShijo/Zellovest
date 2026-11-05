"""Deterministic invoice-to-contract reconciliation tasks."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select
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
    ReconciliationException,
)
from zellovest_shared.db.session import get_sync_engine
from zellovest_shared.logging_conf import get_logger
from zellovest_workers.celery_app import QUEUE_ANALYTICS, celery_app

logger = get_logger(__name__)
_PRICE_TOLERANCE = Decimal("0.01")
_NET_DAYS = re.compile(r"\bnet\s+(\d{1,3})\b", re.IGNORECASE)
_PERCENT_RATE = re.compile(r"(\d+(?:\.\d+)?)\s*%")


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
    invoice_line: InvoiceLineRow,
    contract: ContractRow,
    version: ContractVersionRow,
    term: ContractTermRow,
    rule: ExceptionRule,
    expected: Decimal | None,
    billed: Decimal | None,
    variance_amount: Decimal | None = None,
    variance_pct: float | None = None,
) -> ReconciliationException:
    """Build an immutable exception tied to its exact contract version and term."""
    magnitude = abs(variance_pct or 0)
    severity = "high" if magnitude >= 10 else "medium" if magnitude >= 2 else "low"
    return ReconciliationException(
        tenant_id=invoice.tenant_id,
        invoice_id=invoice.id,
        invoice_line_id=invoice_line.id,
        contract_id=contract.id,
        contract_version_id=version.id,
        contract_term_id=term.id,
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
def reconcile_invoice(tenant_id: str, invoice_id: str) -> dict[str, Any]:
    """Compare invoice lines with the effective vendor contract terms."""
    logger.info("reconcile_started", tenant_id=tenant_id, invoice_id=invoice_id)
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
        if metadata.get("commercial_reconciled_at"):
            logger.info("reconcile_invoice_idempotent", tenant_id=tenant_id, invoice_id=invoice_id)
            return {
                "tenant_id": tenant_id,
                "invoice_id": invoice_id,
                "status": "already_reconciled",
            }
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
        exceptions: list[ReconciliationException] = []
        matched_contract_ids: set[UUID] = set()
        matched_terms: list[tuple[InvoiceLineRow, ContractRow, ContractVersionRow, ContractTermRow]] = []
        review_reason: str | None = None

        for invoice_line in lines:
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
            base_price = _decimal(term.unit_price)
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
                        else None
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
        if exceptions:
            invoice.status = "flagged"
        metadata["commercial_reconciled_at"] = datetime.now(UTC).isoformat()
        metadata["commercial_exception_count"] = len(exceptions)
        invoice.extra = metadata
        session.commit()

        logger.info(
            "reconcile_completed",
            tenant_id=tenant_id,
            invoice_id=invoice_id,
            contract_id=str(invoice.contract_id) if invoice.contract_id else None,
            exception_count=len(exceptions),
        )
        return {
            "tenant_id": tenant_id,
            "invoice_id": invoice_id,
            "status": "flagged" if exceptions else "matched",
            "contract_id": str(invoice.contract_id) if invoice.contract_id else None,
            "exception_count": len(exceptions),
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
