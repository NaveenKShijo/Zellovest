"""Stage 4–7 — Extraction verification, escalation, vendor resolution, upsert.

Stage 4 — Extraction Verification (Jev AI — Noul battery, per field)
    One Jev Decisions API call, all fields in parallel.
    Questions: hallucinated, off_target, incomplete, format_violation, absence_wrong
    Output: P(wrong) per field (noul probability).

Stage 5 — Escalation Gate (deterministic code)
    If any field P(wrong) > threshold (default 0.7) → re-extract with a
    stronger model/higher effort. Else → accept extraction.

Stage 6 — Vendor Resolution (deterministic code)
    Match extracted vendor name → vendors table (by name or domain).
    Insert new vendor if not found (tenant-scoped).

Stage 7 — Postgres Mapping & Upsert (deterministic code)
    Map validated fields → DB columns per doc type.
    Idempotent by document_id / gcs_key / upload_id.
    Insert header + line items.
"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from zellovest_shared.db.models import Contract as ContractRow
from zellovest_shared.db.models import ContractTermsVersion as TermsRow
from zellovest_shared.db.models import Document as DocumentRow
from zellovest_shared.db.models import ExtractionArtifact
from zellovest_shared.db.models import ExtractionProvenance as ProvRow
from zellovest_shared.db.models import Invoice as InvoiceRow
from zellovest_shared.db.models import InvoiceLineItem as InvoiceLineItemRow
from zellovest_shared.db.models import POLineItem as POLineItemRow
from zellovest_shared.db.models import PurchaseOrder as PORow
from zellovest_shared.db.models import Upload as UploadRow
from zellovest_shared.db.models import UploadStatus
from zellovest_shared.db.models import Vendor
from zellovest_shared.db.session import get_sync_engine
from zellovest_shared.logging_conf import get_logger
from zellovest_workers.celery_app import QUEUE_DOCUMENTS, celery_app

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Jev Decisions API (Stage 4)
# ---------------------------------------------------------------------------

_JEV_API_URL = "https://openrouter.ai/api/alpha/decisions"
_JEV_MODEL = "typesafe/jev-1.14"
_JEV_TIMEOUT_SECONDS = 30.0

# Escalation threshold (Stage 5): if any field P(wrong) exceeds this,
# re-extract with a stronger model.
_ESCALATION_THRESHOLD = 0.7

# Fields verified per document type (Stage 4).
_VERIFICATION_FIELDS: dict[str, tuple[str, ...]] = {
    "invoice": ("vendor_name", "invoice_number", "total_amount", "invoice_date"),
    "purchase_order": ("vendor_name", "po_number", "total_amount", "order_date"),
    "contract": (
        "vendor_name", "contract_number", "start_date", "end_date",
        "renewal_date", "notice_period_days", "auto_renew", "terms",
    ),
    "amendment": (
        "vendor_name", "contract_number", "start_date", "end_date",
        "renewal_date", "notice_period_days", "auto_renew", "terms",
    ),
}

_HUMAN_REVIEW_CONFIDENCE_THRESHOLD = 0.80

# Per-field Jev noul question template.
# Each noul question asks "is this specific field wrong?" with yes/no criteria.
_NOUl_QUESTION_TEMPLATE: dict[str, str] = {
    "true": "Yes, this field value is wrong, hallucinated, incomplete, or in the wrong format.",
    "false": "No, this field value looks correct and matches the source text.",
}


class JevVerifyError(Exception):
    """Raised when Jev verification cannot be honored."""


@dataclass
class VerificationResult:
    """Outcome of Stage 4 verification.

    Attributes:
        field_wrong_prob: Mapping of field name → P(wrong) in [0, 1].
        any_wrong: True if any field exceeds the escalation threshold.
        max_wrong_prob: Highest P(wrong) across all fields.
        raw_response: Full Jev response text (audit).
    """

    field_wrong_prob: dict[str, float]
    any_wrong: bool
    max_wrong_prob: float
    raw_response: str = ""


def _build_noul_questions(
    document_type: str, extracted_data: dict[str, Any]
) -> dict[str, Any]:
    """Build Jev noul questions for the fields to verify.

    Args:
        document_type: invoice / purchase_order / contract / amendment.
        extracted_data: Raw LLM-extracted fields.

    Returns:
        Jev ``questions`` dict keyed by question id.
    """
    fields = _VERIFICATION_FIELDS.get(document_type, ())
    questions: dict[str, Any] = {}
    for field in fields:
        value = extracted_data.get(field)
        value_str = str(value) if value is not None else "(not present)"
        questions[f"verify_{field}"] = {
            "type": "noul",
            "instructions": (
                f"Given the document text, is the extracted '{field}' field "
                f"(value: {value_str}) wrong — hallucinated, incomplete, "
                f"in the wrong format, or absent when it should be present?"
            ),
            "criteria": _NOUl_QUESTION_TEMPLATE,
        }
    return questions


def _call_jev_verify(
    document_type: str, extracted_data: dict[str, Any]
) -> VerificationResult:
    """Run Stage 4: Jev Noul battery verification.

    One Decisions API call, all fields in parallel, returns P(wrong) per field.

    Args:
        document_type: invoice / purchase_order / contract / amendment.
        extracted_data: Raw LLM-extracted fields.

    Returns:
        VerificationResult with per-field P(wrong).

    Raises:
        JevVerifyError: On HTTP/auth errors or unparseable response.
    """
    try:
        from zellovest_shared.config import get_settings

        settings = get_settings()
    except Exception as exc:  # pragma: no cover
        raise JevVerifyError(f"settings unavailable: {exc}") from exc

    api_key = settings.jev_api_key
    if not api_key:
        raise JevVerifyError("OPENROUTER_API_KEY is not configured")

    # Flatten extracted data into Jev state as top-level string fields.
    # Jev expects each state field to be a string, not a nested JSON blob.
    state: dict[str, str] = {}
    for key, value in extracted_data.items():
        if isinstance(value, (list, dict)):
            state[key] = json.dumps(value, default=str)
        elif value is None:
            state[key] = ""
        else:
            state[key] = str(value)
    questions = _build_noul_questions(document_type, extracted_data)

    payload = {
        "model": settings.jev_model,
        "state": state,
        "questions": questions,
    }
    logger.info(
        "jev_verify_request",
        document_type=document_type,
        state_keys=list(state.keys()),
        question_keys=list(questions.keys()),
    )
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "X-Title": "Zellovest",
    }

    try:
        response = httpx.post(
            settings.jev_api_url,
            json=payload,
            headers=headers,
            timeout=settings.jev_timeout_seconds,
        )
    except httpx.TimeoutException as exc:
        raise JevVerifyError(f"Jev verify timed out: {exc}") from exc
    except httpx.HTTPError as exc:
        raise JevVerifyError(f"Jev verify request failed: {exc}") from exc

    if response.status_code != 200:
        raise JevVerifyError(
            f"Jev verify HTTP {response.status_code}: {response.text[:300]}"
        )

    try:
        body = response.json()
        answers = body["answers"]
    except (ValueError, KeyError, TypeError) as exc:
        raise JevVerifyError(f"unexpected Jev response shape: {exc}") from exc

    field_wrong_prob: dict[str, float] = {}
    max_prob = 0.0

    for field in _VERIFICATION_FIELDS.get(document_type, ()):
        answer = answers.get(f"verify_{field}")
        if answer is None or answer.get("type") != "noul":
            # Treat missing/invalid answer as uncertain (0.5).
            field_wrong_prob[field] = 0.5
            max_prob = max(max_prob, 0.5)
            continue
        prob = float(answer.get("noul", 0.5))
        prob = round(min(max(prob, 0.0), 1.0), 4)
        field_wrong_prob[field] = prob
        max_prob = max(max_prob, prob)

    any_wrong = max_prob > _ESCALATION_THRESHOLD

    return VerificationResult(
        field_wrong_prob=field_wrong_prob,
        any_wrong=any_wrong,
        max_wrong_prob=max_prob,
        raw_response=response.text[:500],
    )


# ---------------------------------------------------------------------------
# Stage 5 — Escalation gate (deterministic)
# ---------------------------------------------------------------------------


def _should_escalate(result: VerificationResult) -> bool:
    """Return True if any field P(wrong) exceeds the escalation threshold."""
    return result.any_wrong


def _persist_contract_review(
    *,
    tenant_id: str,
    document_id: uuid.UUID,
    document_type: str,
    extracted_data: dict[str, Any],
    verification: VerificationResult,
    overall_confidence: float | None,
    low_confidence_fields: dict[str, float],
) -> dict[str, Any]:
    """Persist uncertain contract terms for a human to review and commit.

    A committed review is never replaced: once a reviewer has verified the
    commercial terms, pipeline retries or re-extraction must not reopen the
    exception or lose the human-verified ledger values.

    Args:
        tenant_id: Owning tenant.
        document_id: Structured document row id.
        document_type: Contract or amendment.
        extracted_data: Uncommitted structured extraction.
        verification: Per-field Jev probability of extraction error.
        overall_confidence: OCR/extraction confidence for the whole document.
        low_confidence_fields: Fields below the human-review threshold mapped
            to their confidence in ``[0, 1]``.

    Returns:
        Review metadata persisted on the upload's extraction artifact.
    """
    fields = _VERIFICATION_FIELDS[document_type]
    field_confidence = {
        field: round(1.0 - verification.field_wrong_prob[field], 4)
        if field in verification.field_wrong_prob
        else 0.0
        for field in fields
    }

    reason_parts: list[str] = []
    if overall_confidence is None:
        reason_parts.append("Overall extraction confidence is unavailable.")
    elif overall_confidence < _HUMAN_REVIEW_CONFIDENCE_THRESHOLD:
        reason_parts.append(
            f"Overall extraction confidence is {overall_confidence:.0%}."
        )
    if low_confidence_fields:
        names = ", ".join(
            f"{field.replace('_', ' ')} ({confidence:.0%})"
            for field, confidence in sorted(
                low_confidence_fields.items(), key=lambda item: item[1]
            )
        )
        reason_parts.append(
            f"Fields below the {int(_HUMAN_REVIEW_CONFIDENCE_THRESHOLD * 100)}% "
            f"threshold: {names}."
        )

    review_data = {
        "status": "pending",
        "document_type": document_type,
        "confidence_threshold": _HUMAN_REVIEW_CONFIDENCE_THRESHOLD,
        "overall_confidence": overall_confidence,
        "field_confidence": field_confidence,
        "low_confidence_fields": low_confidence_fields,
        "data": extracted_data,
        "reason": " ".join(reason_parts) or "Commercial terms require human verification.",
        "created_at": datetime.now(UTC).isoformat(),
    }

    engine = get_sync_engine()
    with Session(engine) as session:
        document = session.get(DocumentRow, document_id)
        if document is None:
            raise ValueError(f"document {document_id} no longer exists")
        if document.upload_id is None:
            raise ValueError(
                f"document {document_id} has no upload id for its review record"
            )
        artifact = session.execute(
            select(ExtractionArtifact).where(
                ExtractionArtifact.upload_id == document.upload_id
            )
        ).scalar_one_or_none()
        if artifact is not None and artifact.review_status == "committed":
            logger.info(
                "contract_review_already_committed",
                tenant_id=tenant_id,
                document_id=str(document_id),
            )
            return artifact.review_data or {}
        if artifact is None:
            artifact = ExtractionArtifact(
                tenant_id=tenant_id,
                upload_id=document.upload_id,
                source_gcs_key=document.gcs_key,
                text_chars=0,
                extraction_method="llm_structured",
                text_snippet="",
            )
            session.add(artifact)
        if artifact is not None:
            artifact.review_status = "pending"
            artifact.review_data = review_data
        document.status = "review_needed"
        session.commit()

    logger.info(
        "contract_review_required",
        tenant_id=tenant_id,
        document_id=str(document_id),
        document_type=document_type,
        field_confidence=field_confidence,
    )
    return review_data


# ---------------------------------------------------------------------------
# Stage 6 — Vendor resolution (deterministic)
# ---------------------------------------------------------------------------


def _resolve_vendor(
    session: Session, tenant_id: str, vendor_name: str | None
) -> uuid.UUID | None:
    """Resolve or create a vendor (tenant-scoped).

    Exact name match → ILIKE substring match → insert new vendor.

    Args:
        session: Open DB session.
        tenant_id: Owning tenant.
        vendor_name: Vendor name extracted from the document.

    Returns:
        Vendor id, or None when no name was provided.
    """
    if not vendor_name:
        return None

    row = session.execute(
        select(Vendor).where(
            Vendor.tenant_id == tenant_id, Vendor.name == vendor_name
        )
    ).scalar_one_or_none()
    if row is not None:
        return row.id

    row = session.execute(
        select(Vendor).where(
            Vendor.tenant_id == tenant_id,
            Vendor.name.ilike(f"%{vendor_name}%"),
        )
    ).scalar_one_or_none()
    if row is not None:
        return row.id

    # Insert new vendor (tenant-scoped).
    new_vendor = Vendor(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        name=vendor_name,
        status="active",
        is_active=True,
    )
    session.add(new_vendor)
    session.flush()
    logger.info(
        "vendor_created",
        tenant_id=tenant_id,
        vendor_id=str(new_vendor.id),
        vendor_name=vendor_name,
    )
    return new_vendor.id


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_date(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    text = str(value)
    try:
        if "T" in text:
            return datetime.fromisoformat(text)
        return datetime.fromisoformat(text + "T00:00:00+00:00")
    except ValueError:
        return None


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _prov_entry(
    *,
    document_id: uuid.UUID,
    tenant_id: str,
    entity_type: str,
    entity_id: uuid.UUID,
    field_name: str,
    field_value: str,
    confidence: float | None,
    page: int | None,
    bbox: list[float] | None,
    method: str,
) -> dict[str, Any]:
    return {
        "document_id": str(document_id),
        "tenant_id": tenant_id,
        "entity_type": entity_type,
        "entity_id": str(entity_id),
        "field_name": field_name,
        "field_value_text": field_value,
        "confidence": round(confidence, 4) if confidence is not None else None,
        "page": page,
        "bbox_json": bbox,
        "extraction_method": method,
        "extracted_at": _now_iso(),
    }


# ---------------------------------------------------------------------------
# Stage 7 — Idempotent upsert writers
# ---------------------------------------------------------------------------


def _upsert_invoice(
    session: Session,
    *,
    tenant_id: str,
    document_id: uuid.UUID,
    data: dict[str, Any],
    vendor_id: uuid.UUID | None,
    provenance: list[dict[str, Any]],
) -> uuid.UUID:
    """Idempotent upsert for invoice header + line items."""
    existing = session.execute(
        select(InvoiceRow).where(
            InvoiceRow.document_id == document_id,
            InvoiceRow.invoice_number == data["invoice_number"],
        )
    ).scalar_one_or_none()
    if existing is not None:
        logger.info(
            "invoice_upsert_idempotent",
            tenant_id=tenant_id,
            document_id=str(document_id),
            invoice_id=str(existing.id),
        )
        return existing.id

    invoice_id = uuid.uuid4()
    now = datetime.now(UTC)

    invoice = InvoiceRow(
        id=invoice_id,
        tenant_id=tenant_id,
        vendor_id=vendor_id,
        document_id=document_id,
        invoice_number=data["invoice_number"],
        invoice_date=_parse_date(data.get("invoice_date")) or now,
        due_date=_parse_date(data.get("due_date")),
        currency=data.get("currency", "USD"),
        subtotal=float(data.get("subtotal", 0) or 0),
        tax_amount=float(data.get("tax_amount", 0) or 0),
        total_amount=float(data.get("total_amount", 0) or 0),
        status="pending",
    )
    session.add(invoice)
    session.flush()

    header_prov = [
        ("invoice_number", data.get("invoice_number", "")),
        ("invoice_date", str(data.get("invoice_date", ""))),
        ("due_date", str(data.get("due_date", ""))),
        ("currency", data.get("currency", "")),
        ("subtotal", str(data.get("subtotal", ""))),
        ("tax_amount", str(data.get("tax_amount", ""))),
        ("total_amount", str(data.get("total_amount", ""))),
    ]
    for field_name, value in header_prov:
        session.add(
            ProvRow(
                id=uuid.uuid4(),
                document_id=document_id,
                tenant_id=tenant_id,
                entity_type="invoice",
                entity_id=invoice_id,
                field_name=field_name,
                field_value_text=str(value),
                confidence=0.85,
                page=None,
                bbox_json=None,
                extraction_method="llm_structured_verified",
                extracted_at=datetime.now(UTC),
            )
        )

    for idx, item in enumerate(data.get("line_items", []), start=1):
        line_id = uuid.uuid4()
        line = InvoiceLineItemRow(
            id=line_id,
            tenant_id=tenant_id,
            invoice_id=invoice_id,
            line_no=idx,
            description=item.get("description", ""),
            product_code=item.get("product_code"),
            quantity=float(item.get("quantity", 1) or 1),
            unit_price=float(item.get("unit_price", 0) or 0),
            total=float(item.get("total", 0) or 0),
        )
        session.add(line)
        session.add(
            ProvRow(
                id=uuid.uuid4(),
                document_id=document_id,
                tenant_id=tenant_id,
                entity_type="invoice_line_item",
                entity_id=line_id,
                field_name=f"line_{idx}_description",
                field_value_text=item.get("description", ""),
                confidence=0.8,
                page=None,
                bbox_json=None,
                extraction_method="llm_structured_verified",
                extracted_at=datetime.now(UTC),
            )
        )
        session.add(
            ProvRow(
                id=uuid.uuid4(),
                document_id=document_id,
                tenant_id=tenant_id,
                entity_type="invoice_line_item",
                entity_id=line_id,
                field_name=f"line_{idx}_total",
                field_value_text=str(line.total),
                confidence=0.8,
                page=None,
                bbox_json=None,
                extraction_method="llm_structured_verified",
                extracted_at=datetime.now(UTC),
            )
        )

    return invoice_id


def _upsert_po(
    session: Session,
    *,
    tenant_id: str,
    document_id: uuid.UUID,
    data: dict[str, Any],
    vendor_id: uuid.UUID | None,
) -> uuid.UUID:
    """Idempotent upsert for purchase-order header + line items."""
    existing = session.execute(
        select(PORow).where(
            PORow.document_id == document_id,
            PORow.po_number == data["po_number"],
        )
    ).scalar_one_or_none()
    if existing is not None:
        logger.info(
            "po_upsert_idempotent",
            tenant_id=tenant_id,
            document_id=str(document_id),
            po_id=str(existing.id),
        )
        return existing.id

    po_id = uuid.uuid4()
    now = datetime.now(UTC)

    po = PORow(
        id=po_id,
        tenant_id=tenant_id,
        vendor_id=vendor_id,
        document_id=document_id,
        po_number=data["po_number"],
        order_date=_parse_date(data.get("order_date")) or now,
        expected_date=_parse_date(data.get("expected_date")),
        currency=data.get("currency", "USD"),
        subtotal=float(data.get("subtotal", 0) or 0),
        tax_amount=float(data.get("tax_amount", 0) or 0),
        total_amount=float(data.get("total_amount", 0) or 0),
        status="draft",
    )
    session.add(po)
    session.flush()

    header_prov = [
        ("po_number", data.get("po_number", "")),
        ("order_date", str(data.get("order_date", ""))),
        ("expected_date", str(data.get("expected_date", ""))),
        ("currency", data.get("currency", "")),
        ("subtotal", str(data.get("subtotal", ""))),
        ("tax_amount", str(data.get("tax_amount", ""))),
        ("total_amount", str(data.get("total_amount", ""))),
    ]
    for field_name, value in header_prov:
        session.add(
            ProvRow(
                id=uuid.uuid4(),
                document_id=document_id,
                tenant_id=tenant_id,
                entity_type="purchase_order",
                entity_id=po_id,
                field_name=field_name,
                field_value_text=str(value),
                confidence=0.85,
                page=None,
                bbox_json=None,
                extraction_method="llm_structured_verified",
                extracted_at=datetime.now(UTC),
            )
        )

    for idx, item in enumerate(data.get("line_items", []), start=1):
        line_id = uuid.uuid4()
        line = POLineItemRow(
            id=line_id,
            tenant_id=tenant_id,
            po_id=po_id,
            line_no=idx,
            description=item.get("description", ""),
            product_code=item.get("product_code"),
            quantity=float(item.get("quantity", 1) or 1),
            unit_price=float(item.get("unit_price", 0) or 0),
            total=float(item.get("total", 0) or 0),
        )
        session.add(line)
        session.add(
            ProvRow(
                id=uuid.uuid4(),
                document_id=document_id,
                tenant_id=tenant_id,
                entity_type="po_line_item",
                entity_id=line_id,
                field_name=f"line_{idx}_description",
                field_value_text=item.get("description", ""),
                confidence=0.8,
                page=None,
                bbox_json=None,
                extraction_method="llm_structured_verified",
                extracted_at=datetime.now(UTC),
            )
        )
        session.add(
            ProvRow(
                id=uuid.uuid4(),
                document_id=document_id,
                tenant_id=tenant_id,
                entity_type="po_line_item",
                entity_id=line_id,
                field_name=f"line_{idx}_total",
                field_value_text=str(line.total),
                confidence=0.8,
                page=None,
                bbox_json=None,
                extraction_method="llm_structured_verified",
                extracted_at=datetime.now(UTC),
            )
        )

    return po_id


def _upsert_contract(
    session: Session,
    *,
    tenant_id: str,
    document_id: uuid.UUID,
    data: dict[str, Any],
    vendor_id: uuid.UUID | None,
) -> uuid.UUID:
    """Idempotent upsert for contract header + terms version."""
    existing = session.execute(
        select(ContractRow).where(
            ContractRow.document_id == document_id,
            ContractRow.contract_number == data["contract_number"],
        )
    ).scalar_one_or_none()
    if existing is not None:
        logger.info(
            "contract_upsert_idempotent",
            tenant_id=tenant_id,
            document_id=str(document_id),
            contract_id=str(existing.id),
        )
        return existing.id

    contract_id = uuid.uuid4()
    now = datetime.now(UTC)

    contract = ContractRow(
        id=contract_id,
        tenant_id=tenant_id,
        vendor_id=vendor_id,
        document_id=document_id,
        contract_number=data["contract_number"],
        title=data.get("title"),
        start_date=_parse_date(data.get("start_date")) or now.date(),
        end_date=(
            _parse_date(data.get("end_date")).date()
            if _parse_date(data.get("end_date"))
            else None
        ),
        renewal_date=(
            _parse_date(data.get("renewal_date")).date()
            if _parse_date(data.get("renewal_date"))
            else None
        ),
        notice_period_days=int(data.get("notice_period_days") or 0)
        if data.get("notice_period_days") is not None
        else None,
        auto_renew=bool(data.get("auto_renew", False)),
        termination_clause=data.get("termination_clause"),
        status="active",
    )
    session.add(contract)
    session.flush()

    header_prov = [
        ("contract_number", data.get("contract_number", "")),
        ("title", data.get("title", "")),
        ("start_date", str(data.get("start_date", ""))),
        ("currency", data.get("currency", "USD")),
    ]
    for field_name, value in header_prov:
        session.add(
            ProvRow(
                id=uuid.uuid4(),
                document_id=document_id,
                tenant_id=tenant_id,
                entity_type="contract",
                entity_id=contract_id,
                field_name=field_name,
                field_value_text=str(value),
                confidence=0.85,
                page=None,
                bbox_json=None,
                extraction_method="llm_structured_verified",
                extracted_at=datetime.now(UTC),
            )
        )

    version_no = 1
    # Determine next version number for this contract.
    max_version = session.execute(
        select(TermsRow.version_no).where(
            TermsRow.contract_id == contract_id
        )
    ).scalars()
    versions = list(max_version)
    if versions:
        version_no = max(versions) + 1

    for line_no, term in enumerate(data.get("terms", []), start=1):
        effective_from = _parse_date(term.get("effective_from")) or now.date()
        effective_to = (
            _parse_date(term.get("effective_to")).date()
            if _parse_date(term.get("effective_to"))
            else None
        )
        terms_row = TermsRow(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            contract_id=contract_id,
            version_no=version_no,
            line_no=line_no,
            product_code=term.get("product_code"),
            description=term.get("description"),
            unit_price=float(term.get("unit_price", 0) or 0),
            currency=term.get("currency", "USD"),
            uom=term.get("uom"),
            qty_min=float(term.get("qty_min"))
            if term.get("qty_min") is not None
            else None,
            qty_max=float(term.get("qty_max"))
            if term.get("qty_max") is not None
            else None,
            discount_pct=float(term.get("discount_pct"))
            if term.get("discount_pct") is not None
            else None,
            tax_rule=term.get("tax_rule"),
            payment_terms=term.get("payment_terms"),
            freight_terms=term.get("freight_terms"),
            escalation_pct=float(term.get("escalation_pct"))
            if term.get("escalation_pct") is not None
            else None,
            effective_from=effective_from,
            effective_to=effective_to,
            amendment_document_id=document_id,
        )
        session.add(terms_row)
        session.add(
            ProvRow(
                id=uuid.uuid4(),
                document_id=document_id,
                tenant_id=tenant_id,
                entity_type="contract_term",
                entity_id=terms_row.id,
                field_name=f"term_{term.get('product_code', 'unknown')}_unit_price",
                field_value_text=str(terms_row.unit_price),
                confidence=0.8,
                page=None,
                bbox_json=None,
                extraction_method="llm_structured_verified",
                extracted_at=datetime.now(UTC),
            )
        )

    return contract_id


# ---------------------------------------------------------------------------
# Stages 4–7 combined task
# ---------------------------------------------------------------------------


@celery_app.task(
    name="zellovest.workers.tasks.document_verify.verify_and_upsert",
    queue=QUEUE_DOCUMENTS,
    max_retries=3,
)
def verify_and_upsert(
    tenant_id: str,
    document_id: str,
    document_type: str,
    extracted_data: dict[str, Any],
    gcs_key: str = "",
    filename: str = "",
    reextract_attempt: int = 0,
    **kwargs: Any,
) -> dict[str, Any]:
    """Stages 4–7: verify → escalation gate → vendor resolution → idempotent upsert.

    Args:
        tenant_id: Owning tenant.
        document_id: Documents row id (string).
        document_type: invoice / purchase_order / contract / amendment.
        extracted_data: Raw LLM-extracted fields from Stage 3b.
        gcs_key: GCS object key.
        filename: Original filename.
        reextract_attempt: Current re-extraction attempt count (0 = first).
        **kwargs: Ignored extras.

    Returns:
        Dict with entity_id, status, verification results, and provenance count.
    """
    engine = get_sync_engine()
    extraction_confidence: float | None = None
    review_status: str | None = None
    with Session(engine) as session:
        try:
            doc_key = uuid.UUID(document_id)
        except ValueError:
            logger.warning("verify_bad_id", document_id=document_id)
            return {"document_id": document_id, "status": "failed", "error": "bad id"}

        doc = session.get(DocumentRow, doc_key)
        if doc is None:
            logger.warning("verify_not_found", document_id=document_id)
            return {"document_id": document_id, "status": "failed", "error": "not found"}

        artifact = session.execute(
            select(ExtractionArtifact).where(
                ExtractionArtifact.upload_id == doc.upload_id
            )
        ).scalar_one_or_none()
        if artifact is not None:
            review_status = artifact.review_status
            if artifact.extraction_confidence is not None:
                extraction_confidence = float(artifact.extraction_confidence)

    # A human has already verified this document's commercial terms. Never
    # re-run automated verification or overwrite the committed ledger values.
    if review_status == "committed":
        logger.info(
            "verify_skipped_committed_review",
            tenant_id=tenant_id,
            document_id=document_id,
            document_type=document_type,
        )
        return {
            "tenant_id": tenant_id,
            "document_id": document_id,
            "document_type": document_type,
            "status": "already_committed",
        }

    # ------------------------------------------------------------------
    # Stage 4 — Jev Noul battery verification
    # ------------------------------------------------------------------
    try:
        verification = _call_jev_verify(document_type, extracted_data)
    except JevVerifyError as exc:
        logger.warning(
            "verify_jev_failed",
            tenant_id=tenant_id,
            document_id=document_id,
            error_class="JevVerifyError",
            error=str(exc),
        )
        # Cannot verify → accept extraction (degrade gracefully).
        verification = VerificationResult(
            field_wrong_prob={},
            any_wrong=False,
            max_wrong_prob=0.0,
            raw_response=str(exc),
        )

    logger.info(
        "document_verified",
        tenant_id=tenant_id,
        document_id=document_id,
        document_type=document_type,
        field_wrong_prob=verification.field_wrong_prob,
        any_wrong=verification.any_wrong,
        max_wrong_prob=verification.max_wrong_prob,
    )

    # Commercial terms remain provisional until a human confirms every
    # contract field meets the review confidence threshold. A low-quality
    # overall extraction is also escalated, even when Jev is confident.
    if document_type in {"contract", "amendment"}:
        field_confidence = {
            field: round(1.0 - verification.field_wrong_prob[field], 4)
            if field in verification.field_wrong_prob
            else 0.0
            for field in _VERIFICATION_FIELDS[document_type]
        }
        low_confidence_fields = {
            field: confidence
            for field, confidence in field_confidence.items()
            if confidence < _HUMAN_REVIEW_CONFIDENCE_THRESHOLD
        }
        overall_is_low = (
            extraction_confidence is None
            or extraction_confidence < _HUMAN_REVIEW_CONFIDENCE_THRESHOLD
        )
        if low_confidence_fields or overall_is_low:
            review_data = _persist_contract_review(
                tenant_id=tenant_id,
                document_id=doc_key,
                document_type=document_type,
                extracted_data=extracted_data,
                verification=verification,
                overall_confidence=extraction_confidence,
                low_confidence_fields=low_confidence_fields,
            )
            return {
                "tenant_id": tenant_id,
                "document_id": document_id,
                "document_type": document_type,
                "status": "review_needed",
                "review": review_data,
            }

    # ------------------------------------------------------------------
    # Stage 5 — Escalation gate
    # ------------------------------------------------------------------
    if verification.any_wrong and reextract_attempt < 2:
        logger.info(
            "verify_escalating",
            tenant_id=tenant_id,
            document_id=document_id,
            max_wrong_prob=verification.max_wrong_prob,
            attempt=reextract_attempt + 1,
        )
        # Re-extract with stronger model via Stage 3b, then re-verify.
        from zellovest_workers.tasks.document_structured_extract import (
            extract_structured,
        )

        # Fetch fresh text for re-extraction.
        engine = get_sync_engine()
        with Session(engine) as session:
            doc = session.get(DocumentRow, doc_key)
            text = ""
            if doc is not None:
                artifact = session.execute(
                    select(ExtractionArtifact).where(
                        ExtractionArtifact.upload_id == doc.upload_id
                    )
                ).scalar_one_or_none()
                text = artifact.text_snippet if artifact is not None else ""

        if text:
            reextract_result = extract_structured.delay(
                tenant_id=tenant_id,
                document_id=document_id,
                document_type=document_type,
                gcs_key=gcs_key or doc.gcs_key,
                filename=filename or doc.filename,
            )
            return {
                "tenant_id": tenant_id,
                "document_id": document_id,
                "document_type": document_type,
                "status": "escalated_for_reextract",
                "reason": f"max P(wrong) {verification.max_wrong_prob} > threshold {_ESCALATION_THRESHOLD}",
                "verification": {
                    "field_wrong_prob": verification.field_wrong_prob,
                    "max_wrong_prob": verification.max_wrong_prob,
                },
                "reextract_task_id": str(reextract_result.id),
            }

    # ------------------------------------------------------------------
    # Stage 6 — Vendor resolution
    # ------------------------------------------------------------------
    vendor_name = extracted_data.get("vendor_name")
    vendor_id: uuid.UUID | None = None
    try:
        engine = get_sync_engine()
        with Session(engine) as session:
            vendor_id = _resolve_vendor(session, tenant_id, vendor_name)
            session.commit()
    except Exception as exc:
        logger.warning(
            "verify_vendor_resolve_failed",
            tenant_id=tenant_id,
            document_id=document_id,
            error_class=type(exc).__name__,
        )

    # ------------------------------------------------------------------
    # Stage 7 — Idempotent Postgres upsert
    # ------------------------------------------------------------------
    try:
        engine = get_sync_engine()
        with Session(engine) as session:
            if document_type == "invoice":
                entity_id = _upsert_invoice(
                    session,
                    tenant_id=tenant_id,
                    document_id=doc_key,
                    data=extracted_data,
                    vendor_id=vendor_id,
                    provenance=[],  # provenance written inside _upsert_invoice
                )
            elif document_type == "purchase_order":
                entity_id = _upsert_po(
                    session,
                    tenant_id=tenant_id,
                    document_id=doc_key,
                    data=extracted_data,
                    vendor_id=vendor_id,
                )
            else:  # contract / amendment
                entity_id = _upsert_contract(
                    session,
                    tenant_id=tenant_id,
                    document_id=doc_key,
                    data=extracted_data,
                    vendor_id=vendor_id,
                )

            # Update document status.
            doc = session.get(DocumentRow, doc_key)
            if doc is not None:
                doc.status = "extracted"
            session.commit()

        logger.info(
            "document_upserted",
            tenant_id=tenant_id,
            document_id=document_id,
            document_type=document_type,
            entity_id=str(entity_id),
            vendor_id=str(vendor_id) if vendor_id else None,
        )
        return {
            "tenant_id": tenant_id,
            "document_id": document_id,
            "document_type": document_type,
            "entity_id": str(entity_id),
            "vendor_id": str(vendor_id) if vendor_id else None,
            "vendor_name": vendor_name,
            "status": "extracted",
            "verification": {
                "field_wrong_prob": verification.field_wrong_prob,
                "max_wrong_prob": verification.max_wrong_prob,
                "any_wrong": verification.any_wrong,
            },
        }
    except Exception as exc:
        logger.warning(
            "verify_upsert_failed",
            tenant_id=tenant_id,
            document_id=document_id,
            error_class=type(exc).__name__,
        )
        try:
            engine = get_sync_engine()
            with Session(engine) as session:
                doc = session.get(DocumentRow, doc_key)
                if doc is not None:
                    doc.status = "review_needed"
                    session.commit()
        except Exception:
            pass
        return {
            "tenant_id": tenant_id,
            "document_id": document_id,
            "status": "review_needed",
            "error": str(exc),
        }
