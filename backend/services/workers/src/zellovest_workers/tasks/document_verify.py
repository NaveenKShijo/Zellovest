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
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from zellovest_shared.db.models import Contract as ContractRow
from zellovest_shared.db.models import ContractChangeType
from zellovest_shared.db.models import ContractLine as ContractLineRow
from zellovest_shared.db.models import ContractTermsVersion as TermsRow
from zellovest_shared.db.models import ContractVersion as ContractVersionRow
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
from zellovest_shared.contract_versioning import (
    AmbiguousContractLineError,
    match_contract_line,
    normalize_contract_number,
)
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


class ContractReviewRequired(ValueError):
    """Raised when an amendment needs a human to resolve its lineage or lines."""

    def __init__(self, message: str, *, parent_required: bool = False) -> None:
        """Store the reviewer-facing reason and whether a parent is required."""
        super().__init__(message)
        self.parent_required = parent_required


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
    review_reason: str | None = None,
    parent_contract_required: bool = False,
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
    if review_reason:
        reason_parts.append(review_reason)

    review_data = {
        "status": "pending",
        "document_type": document_type,
        "confidence_threshold": _HUMAN_REVIEW_CONFIDENCE_THRESHOLD,
        "overall_confidence": overall_confidence,
        "field_confidence": field_confidence,
        "low_confidence_fields": low_confidence_fields,
        "data": extracted_data,
        "reason": " ".join(reason_parts) or "Commercial terms require human verification.",
        "parent_contract_required": parent_contract_required,
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
    document_type: str,
    data: dict[str, Any],
    vendor_id: uuid.UUID | None,
) -> uuid.UUID:
    """Append a source-backed contract version without duplicating its header."""
    contract_number = str(data.get("contract_number") or "").strip()
    normalized_number = normalize_contract_number(contract_number)
    if not normalized_number:
        raise ContractReviewRequired("A contract number is required before ledger commit.")
    if vendor_id is None:
        raise ContractReviewRequired("A canonical vendor must be resolved before ledger commit.")

    raw_change_type = str(data.get("change_type") or "").casefold()
    if not raw_change_type:
        raw_change_type = "amendment" if document_type == "amendment" else "original"
    try:
        change_type = ContractChangeType(raw_change_type)
    except ValueError as exc:
        raise ContractReviewRequired(
            "Select whether this document is an original, amendment, renewal, or price revision."
        ) from exc
    if document_type == "amendment" and change_type == ContractChangeType.ORIGINAL:
        raise ContractReviewRequired(
            "This document is classified as an amendment and needs a parent contract.",
            parent_required=True,
        )

    already_committed = session.execute(
        select(ContractVersionRow).where(
            ContractVersionRow.tenant_id == tenant_id,
            ContractVersionRow.source_document_id == document_id,
        )
    ).scalar_one_or_none()
    if already_committed is not None:
        return already_committed.contract_id

    vendor_contracts = session.execute(
        select(ContractRow)
        .where(
            ContractRow.tenant_id == tenant_id,
            ContractRow.vendor_id == vendor_id,
        )
        .with_for_update()
    ).scalars().all()
    exact_matches = [
        contract
        for contract in vendor_contracts
        if normalize_contract_number(contract.contract_number) == normalized_number
    ]

    if change_type == ContractChangeType.ORIGINAL:
        if exact_matches:
            existing = next(
                (contract for contract in exact_matches if contract.document_id == document_id),
                None,
            )
            if existing is not None:
                return existing.id
            raise ContractReviewRequired(
                "A contract with this vendor and number already exists. Confirm whether this document amends or renews it.",
                parent_required=True,
            )
        contract = ContractRow(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            vendor_id=vendor_id,
            document_id=document_id,
            contract_number=contract_number,
            title=data.get("title"),
            start_date=(
                _parse_date(data.get("start_date")).date()
                if _parse_date(data.get("start_date"))
                else datetime.now(UTC).date()
            ),
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
            notice_period_days=int(data["notice_period_days"])
            if data.get("notice_period_days") is not None
            else None,
            auto_renew=bool(data.get("auto_renew", False)),
            termination_clause=data.get("termination_clause"),
            status="active",
        )
        session.add(contract)
        session.flush()
    else:
        if len(exact_matches) != 1:
            raise ContractReviewRequired(
                "Select the parent contract before this amendment can be committed.",
                parent_required=True,
            )
        contract = exact_matches[0]

    normalized_terms: list[dict[str, Any]] = []
    for incoming in data.get("terms") or []:
        effective_from_value = _parse_date(incoming.get("effective_from"))
        if effective_from_value is None:
            effective_from_value = _parse_date(data.get("start_date")) or datetime.now(UTC)
        effective_to_value = _parse_date(incoming.get("effective_to"))
        normalized_terms.append(
            {
                **incoming,
                "effective_from": effective_from_value.date(),
                "effective_to": effective_to_value.date() if effective_to_value else None,
            }
        )
    if not normalized_terms:
        raise ContractReviewRequired("At least one commercial pricing line is required.")
    if any(
        term["effective_to"] is not None
        and term["effective_to"] < term["effective_from"]
        for term in normalized_terms
    ):
        raise ContractReviewRequired("A pricing line expires before its effective date.")

    version_start = min(term["effective_from"] for term in normalized_terms)
    latest = session.execute(
        select(ContractVersionRow)
        .where(
            ContractVersionRow.tenant_id == tenant_id,
            ContractVersionRow.contract_id == contract.id,
        )
        .order_by(ContractVersionRow.version_no.desc())
        .limit(1)
        .with_for_update()
    ).scalar_one_or_none()
    if latest is not None and version_start <= latest.effective_from:
        raise ContractReviewRequired(
            "This change is backdated relative to the latest version and needs reviewer rebase."
        )

    parent_terms = (
        session.execute(
            select(TermsRow)
            .where(
                TermsRow.tenant_id == tenant_id,
                TermsRow.contract_version_id == latest.id,
            )
            .order_by(TermsRow.line_no)
            .with_for_update()
        ).scalars().all()
        if latest is not None
        else []
    )
    assignments: list[tuple[dict[str, Any], TermsRow | None, uuid.UUID]] = []
    matched: dict[str, dict[str, Any]] = {}
    next_line_no = max((term.line_no for term in parent_terms), default=0) + 1
    for term in normalized_terms:
        try:
            old = match_contract_line(term, parent_terms)
        except AmbiguousContractLineError as exc:
            raise ContractReviewRequired(str(exc)) from exc
        if old is not None:
            line_id = old.contract_line_id
            if str(line_id) in matched:
                raise ContractReviewRequired(
                    "Multiple amendment rows map to one existing product line; map them separately."
                )
            matched[str(line_id)] = term
        else:
            line = ContractLineRow(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                contract_id=contract.id,
                initial_document_id=document_id,
            )
            session.add(line)
            session.flush()
            line_id = line.id
        assignments.append((term, old, line_id))

    version_no = (latest.version_no if latest else 0) + 1
    version = ContractVersionRow(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        contract_id=contract.id,
        version_no=version_no,
        source_document_id=document_id,
        parent_version_id=latest.id if latest else None,
        change_type=change_type,
        effective_from=version_start,
        title=data.get("title") or contract.title,
        contract_start_date=(
            (_parse_date(data.get("start_date")) or datetime.combine(version_start, datetime.min.time())).date()
        ),
        contract_end_date=(
            _parse_date(data.get("end_date")).date()
            if _parse_date(data.get("end_date"))
            else None
        ),
        renewal_date=(
            _parse_date(data.get("renewal_date")).date()
            if _parse_date(data.get("renewal_date"))
            else None
        ),
        notice_period_days=int(data["notice_period_days"])
        if data.get("notice_period_days") is not None
        else None,
        auto_renew=bool(data.get("auto_renew", contract.auto_renew)),
        termination_clause=data.get("termination_clause") or contract.termination_clause,
    )
    session.add(version)
    session.flush()
    if latest is not None:
        latest.effective_to = version_start - timedelta(days=1)

    for old in parent_terms:
        if old.effective_to is not None and old.effective_to < version_start:
            continue
        if old.effective_from > version_start:
            future_change = matched.get(str(old.contract_line_id))
            if future_change is not None:
                changed_from = future_change["effective_from"]
                if changed_from < old.effective_from:
                    raise ContractReviewRequired(
                        "A changed product line cannot take effect before its scheduled start."
                    )
                close_date = changed_from - timedelta(days=1)
                old.effective_to = min(old.effective_to or close_date, close_date)
            continue
        old_line_id = str(old.contract_line_id)
        changed = matched.get(old_line_id)
        old_end = old.effective_to
        if changed is None:
            old.effective_to = min(old_end or version_start - timedelta(days=1), version_start - timedelta(days=1))
            session.add(
                TermsRow(
                    id=uuid.uuid4(),
                    tenant_id=tenant_id,
                    contract_id=contract.id,
                    contract_version_id=version.id,
                    contract_line_id=old.contract_line_id,
                    version_no=version_no,
                    line_no=old.line_no,
                    product_code=old.product_code,
                    description=old.description,
                    unit_price=old.unit_price,
                    currency=old.currency,
                    uom=old.uom,
                    qty_min=old.qty_min,
                    qty_max=old.qty_max,
                    discount_pct=old.discount_pct,
                    tax_rule=old.tax_rule,
                    payment_terms=old.payment_terms,
                    freight_terms=old.freight_terms,
                    escalation_pct=old.escalation_pct,
                    effective_from=version_start,
                    effective_to=old_end,
                    amendment_document_id=document_id,
                )
            )
            continue

        changed_from = changed["effective_from"]
        if changed_from <= old.effective_from:
            raise ContractReviewRequired(
                "A changed product line cannot take effect before its current line."
            )
        old.effective_to = min(old_end or changed_from - timedelta(days=1), changed_from - timedelta(days=1))
        if changed_from > version_start:
            carry_end = min(old_end or changed_from - timedelta(days=1), changed_from - timedelta(days=1))
            if old.effective_from <= carry_end:
                session.add(
                    TermsRow(
                        id=uuid.uuid4(),
                        tenant_id=tenant_id,
                        contract_id=contract.id,
                        contract_version_id=version.id,
                        contract_line_id=old.contract_line_id,
                        version_no=version_no,
                        line_no=next_line_no,
                        product_code=old.product_code,
                        description=old.description,
                        unit_price=old.unit_price,
                        currency=old.currency,
                        uom=old.uom,
                        qty_min=old.qty_min,
                        qty_max=old.qty_max,
                        discount_pct=old.discount_pct,
                        tax_rule=old.tax_rule,
                        payment_terms=old.payment_terms,
                        freight_terms=old.freight_terms,
                        escalation_pct=old.escalation_pct,
                        effective_from=version_start,
                        effective_to=carry_end,
                        amendment_document_id=document_id,
                    )
                )
                next_line_no += 1

    for term, old, line_id in assignments:
        term_id = uuid.uuid4()
        line_no = old.line_no if old is not None else next_line_no
        if old is None:
            next_line_no += 1
        terms_row = TermsRow(
            id=term_id,
            tenant_id=tenant_id,
            contract_id=contract.id,
            contract_version_id=version.id,
            contract_line_id=line_id,
            version_no=version_no,
            line_no=line_no,
            product_code=term.get("product_code"),
            description=term.get("description"),
            unit_price=float(term.get("unit_price", 0) or 0),
            currency=str(term.get("currency") or "USD").upper(),
            uom=term.get("uom"),
            qty_min=float(term["qty_min"]) if term.get("qty_min") is not None else None,
            qty_max=float(term["qty_max"]) if term.get("qty_max") is not None else None,
            discount_pct=(float(term["discount_pct"]) if term.get("discount_pct") is not None else None),
            tax_rule=term.get("tax_rule"),
            payment_terms=term.get("payment_terms"),
            freight_terms=term.get("freight_terms"),
            escalation_pct=(float(term["escalation_pct"]) if term.get("escalation_pct") is not None else None),
            effective_from=term["effective_from"],
            effective_to=term["effective_to"],
            amendment_document_id=document_id,
        )
        session.add(terms_row)
        session.add(
            ProvRow(
                id=uuid.uuid4(),
                document_id=document_id,
                tenant_id=tenant_id,
                entity_type="contract_term",
                entity_id=term_id,
                field_name=f"term_{term.get('product_code') or 'unknown'}_unit_price",
                field_value_text=str(terms_row.unit_price),
                confidence=0.85,
                extraction_method="llm_structured_verified",
                extracted_at=datetime.now(UTC),
            )
        )

    for field_name, value in (
        ("contract_number", contract_number),
        ("title", data.get("title", "")),
        ("start_date", data.get("start_date", "")),
    ):
        session.add(
            ProvRow(
                id=uuid.uuid4(),
                document_id=document_id,
                tenant_id=tenant_id,
                entity_type="contract",
                entity_id=contract.id,
                field_name=field_name,
                field_value_text=str(value),
                confidence=0.85,
                extraction_method="llm_structured_verified",
                extracted_at=datetime.now(UTC),
            )
        )
    return contract.id


def _link_document_vendor(
    session: Session,
    *,
    document: DocumentRow,
    vendor_id: uuid.UUID | None,
) -> None:
    """Copy a resolved vendor to the document and its upload index rows.

    Args:
        session: Open database session used to load the upload row.
        document: Document whose typed ledger row was just persisted.
        vendor_id: Resolved canonical vendor ID, if resolution succeeded.

    Notes:
        A ``None`` vendor ID is intentionally a no-op. This prevents an
        extraction without a vendor from clearing a reviewed or previously
        resolved vendor link.
    """
    if vendor_id is None:
        return

    document.vendor_id = vendor_id
    if document.upload_id is None:
        return

    upload = session.get(UploadRow, document.upload_id)
    if upload is not None:
        upload.vendor_id = str(vendor_id)


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
    contract_low_confidence_fields: dict[str, float] = {}
    if document_type in {"contract", "amendment"}:
        field_confidence = {
            field: round(1.0 - verification.field_wrong_prob[field], 4)
            if field in verification.field_wrong_prob
            else 0.0
            for field in _VERIFICATION_FIELDS[document_type]
        }
        contract_low_confidence_fields = {
            field: confidence
            for field, confidence in field_confidence.items()
            if confidence < _HUMAN_REVIEW_CONFIDENCE_THRESHOLD
        }
        overall_is_low = (
            extraction_confidence is None
            or extraction_confidence < _HUMAN_REVIEW_CONFIDENCE_THRESHOLD
        )
        if contract_low_confidence_fields or overall_is_low:
            review_data = _persist_contract_review(
                tenant_id=tenant_id,
                document_id=doc_key,
                document_type=document_type,
                extracted_data=extracted_data,
                verification=verification,
                overall_confidence=extraction_confidence,
                low_confidence_fields=contract_low_confidence_fields,
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
                    document_type=document_type,
                    data=extracted_data,
                    vendor_id=vendor_id,
                )

            # Update document status.
            doc = session.get(DocumentRow, doc_key)
            if doc is not None:
                doc.status = "extracted"

                # Documents Explorer reads the canonical vendor link from the
                # document/upload rows. Keep those links in sync with the
                # typed ledger row written above. A missing resolution must
                # not clear a vendor that was set by a reviewer or an earlier
                # successful extraction.
                _link_document_vendor(
                    session,
                    document=doc,
                    vendor_id=vendor_id,
                )
            session.commit()

        if document_type == "invoice":
            try:
                from zellovest_workers.tasks.ap_audit import reconcile_invoice

                task_result = reconcile_invoice.delay(
                    tenant_id=tenant_id,
                    invoice_id=str(entity_id),
                )
                logger.info(
                    "invoice_reconciliation_enqueued",
                    tenant_id=tenant_id,
                    invoice_id=str(entity_id),
                    task_id=str(task_result.id),
                )
            except Exception as enqueue_error:
                logger.warning(
                    "invoice_reconciliation_enqueue_failed",
                    tenant_id=tenant_id,
                    invoice_id=str(entity_id),
                    error_class=type(enqueue_error).__name__,
                )

        logger.info(
            "document_upserted",
            tenant_id=tenant_id,
            document_id=document_id,
            document_type=document_type,
            entity_id=str(entity_id),
            vendor_id=str(vendor_id) if vendor_id else None,
        )
        try:
            from zellovest_workers.tasks.document_index import index_document_task

            index_result = index_document_task.delay(
                tenant_id=tenant_id, document_id=document_id
            )
            logger.info(
                "rag_index_enqueued",
                tenant_id=tenant_id,
                document_id=document_id,
                document_type=document_type,
                reason="refresh_after_vendor_resolution",
                task_id=str(index_result.id),
            )
        except Exception as enqueue_error:
            logger.error(
                "rag_index_enqueue_failed",
                tenant_id=tenant_id,
                document_id=document_id,
                error_class=type(enqueue_error).__name__,
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
    except ContractReviewRequired as exc:
        review_data = _persist_contract_review(
            tenant_id=tenant_id,
            document_id=doc_key,
            document_type=document_type,
            extracted_data=extracted_data,
            verification=verification,
            overall_confidence=extraction_confidence,
            low_confidence_fields=contract_low_confidence_fields,
            review_reason=str(exc),
            parent_contract_required=exc.parent_required,
        )
        logger.info(
            "contract_lineage_review_required",
            tenant_id=tenant_id,
            document_id=document_id,
            parent_contract_required=exc.parent_required,
        )
        return {
            "tenant_id": tenant_id,
            "document_id": document_id,
            "document_type": document_type,
            "status": "review_needed",
            "review": review_data,
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
