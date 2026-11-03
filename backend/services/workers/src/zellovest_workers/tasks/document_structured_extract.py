"""Stage 3b — Structured extraction (LLM → raw JSON fields only).

Reads the extracted text of a promoted ``documents`` row and calls Groq
chat-completions with a type-specific JSON schema. Returns the **raw
extracted fields** — no database writes, no vendor resolution, no
provenance insertion. Those concerns belong to Stages 4–7
(``document_verify``).

Supported document types: invoice, purchase_order, contract, amendment.

On LLM failure the document is marked ``review_needed`` — the pipeline
never stalls, and a human can pick it up from the review queue.
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

from zellovest_shared.db.models import Document as DocumentRow
from zellovest_shared.db.session import get_sync_engine
from zellovest_shared.logging_conf import get_logger
from zellovest_shared.workers.gcs_client import GcsStorageReader
from zellovest_workers.celery_app import QUEUE_DOCUMENTS, celery_app

logger = get_logger(__name__)

# Document types this stage can extract.
_EXTRACTABLE_TYPES = frozenset(
    {"invoice", "purchase_order", "contract", "amendment"}
)

# Per-document-type JSON-schema prompts for Groq.


def _invoice_prompt(text: str, filename: str) -> str:
    return f"""\
You extract structured invoice data from OCR'd document text. Return ONLY a
JSON object with this exact shape:

{{
  "invoice_number": "<string, required>",
  "invoice_date": "<ISO-8601 datetime, required>",
  "due_date": "<ISO-8601 datetime or null>",
  "currency": "<ISO currency code, default USD>",
  "subtotal": <number, required>,
  "tax_amount": <number, default 0>,
  "total_amount": <number, required>,
  "vendor_name": "<string or null>",
  "line_items": [
    {{
      "description": "<string, required>",
      "product_code": "<string or null>",
      "quantity": <number, default 1>,
      "unit_price": <number, required>,
      "total": <number, required>
    }}
  ]
}}

Rules:
- All monetary values are plain numbers (no currency symbols).
- invoice_number is the document's own number, not a PO number.
- If a line has no explicit quantity, use 1.
- line_items.total should equal quantity × unit_price per line.
- Omit unknown fields; do not invent line items that are not in the text.

Filename: {filename}

Extracted text (first 8000 chars):
{text[:8000]}
"""


def _po_prompt(text: str, filename: str) -> str:
    return f"""\
You extract structured purchase-order data from OCR'd document text. Return ONLY a
JSON object with this exact shape:

{{
  "po_number": "<string, required>",
  "order_date": "<ISO-8601 datetime, required>",
  "expected_date": "<ISO-8601 datetime or null>",
  "currency": "<ISO currency code, default USD>",
  "subtotal": <number, required>,
  "tax_amount": <number, default 0>,
  "total_amount": <number, required>,
  "vendor_name": "<string or null>",
  "line_items": [
    {{
      "description": "<string, required>",
      "product_code": "<string or null>",
      "quantity": <number, required>,
      "unit_price": <number, required>,
      "total": <number, required>
    }}
  ]
}}

Rules:
- po_number is the PO's own number.
- All monetary values are plain numbers.
- Omit unknown fields; do not invent line items.

Filename: {filename}

Extracted text (first 8000 chars):
{text[:8000]}
"""


def _contract_prompt(text: str, filename: str) -> str:
    return f"""\
You extract structured contract data from OCR'd document text. Return ONLY a
JSON object with this exact shape:

{{
  "contract_number": "<string, required>",
  "title": "<string or null>",
  "start_date": "<ISO-8601 date, required>",
  "end_date": "<ISO-8601 date or null>",
  "renewal_date": "<ISO-8601 date or null>",
  "notice_period_days": <integer or null>,
  "auto_renew": <boolean, default false>,
  "termination_clause": "<string or null>",
  "vendor_name": "<string or null>",
  "terms": [
    {{
      "product_code": "<string or null>",
      "description": "<string or null>",
      "unit_price": <number>,
      "currency": "<ISO currency code, default USD>",
      "uom": "<unit of measure or null>",
      "qty_min": <number or null>,
      "qty_max": <number or null>,
      "discount_pct": <number or null>,
      "tax_rule": "<string or null>",
      "payment_terms": "<string or null>",
      "freight_terms": "<string or null>",
      "escalation_pct": <number or null>,
      "effective_from": "<ISO-8601 date, required>",
      "effective_to": "<ISO-8601 date or null>"
    }}
  ]
}}

Rules:
- One terms row per distinct pricing tier / product line in the contract.
- effective_from is required for each terms row.
- Omit unknown fields; do not invent terms not in the text.

Filename: {filename}

Extracted text (first 8000 chars):
{text[:8000]}
"""


_PROMPTS: dict[str, Any] = {
    "invoice": _invoice_prompt,
    "purchase_order": _po_prompt,
    "contract": _contract_prompt,
    "amendment": _contract_prompt,  # amendments share contract schema
}


class StructuredExtractError(Exception):
    """Raised when structured extraction cannot be honored."""


def _call_llm(prompt: str) -> dict[str, Any]:
    """Call Groq chat-completions and return parsed JSON."""
    try:
        from zellovest_shared.config import get_settings

        settings = get_settings()
    except Exception as exc:  # pragma: no cover
        raise StructuredExtractError(f"settings unavailable: {exc}") from exc

    api_key = settings.groq_api_key
    if not api_key:
        raise StructuredExtractError("GROQ_API_KEY is not configured")

    payload = {
        "model": settings.groq_model,
        "temperature": 0.0,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are a precise data-extraction engine for a procurement "
                    "platform. You return ONLY valid JSON matching the requested "
                    "schema, with no markdown fences or extra prose."
                ),
            },
            {"role": "user", "content": prompt},
        ],
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "X-Title": "Zellovest",
    }

    try:
        response = httpx.post(
            settings.groq_api_url,
            json=payload,
            headers=headers,
            timeout=settings.groq_timeout_seconds,
        )
    except httpx.TimeoutException as exc:
        raise StructuredExtractError(f"Groq request timed out: {exc}") from exc
    except httpx.HTTPError as exc:
        raise StructuredExtractError(f"Groq request failed: {exc}") from exc

    if response.status_code != 200:
        raise StructuredExtractError(
            f"Groq HTTP {response.status_code}: {response.text[:300]}"
        )

    try:
        body = response.json()
        content = body["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise StructuredExtractError(f"unexpected LLM response shape: {exc}") from exc

    # Tolerate markdown fences.
    candidate = content.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", candidate, re.DOTALL)
    if fenced:
        candidate = fenced.group(1).strip()
    try:
        return json.loads(candidate)
    except ValueError as exc:
        raise StructuredExtractError(f"unparseable LLM JSON: {exc}") from exc


def _parse_date(value: Any) -> datetime | None:
    """Parse an ISO-8601 date/datetime string into a tz-aware datetime."""
    if value is None or value == "":
        return None
    text = str(value)
    try:
        if "T" in text:
            return datetime.fromisoformat(text)
        return datetime.fromisoformat(text + "T00:00:00+00:00")
    except ValueError:
        return None


def _download_full_text(gcs_key: str) -> str:
    """Read the full extraction artifact from GCS (fallback for long docs)."""
    try:
        from zellovest_shared.config import get_settings

        settings = get_settings()
        bucket = settings.gcs_raw_bucket
    except Exception:
        bucket = ""
    if not bucket or not gcs_key:
        return ""
    try:
        data = GcsStorageReader().download_bytes(bucket=bucket, key=gcs_key)
        if data is None:
            return ""
        return data.decode("utf-8", errors="replace")
    except Exception as exc:
        logger.warning(
            "structured_extract_gcs_read_failed",
            gcs_key=gcs_key,
            error_class=type(exc).__name__,
        )
        return ""


@dataclass
class ExtractedFields:
    """Raw LLM-extracted fields, ready for Stage 4 verification.

    Attributes:
        document_type: The type that was extracted.
        data: Parsed JSON fields from the LLM.
        raw_response: Full LLM response text (audit).
        confidence: Overall extraction confidence (0-1).
    """

    document_type: str
    data: dict[str, Any]
    raw_response: str = ""
    confidence: float = 0.0


@celery_app.task(
    name="zellovest.workers.tasks.document_structured_extract.extract_structured",
    queue=QUEUE_DOCUMENTS,
    max_retries=3,
)
def extract_structured(
    tenant_id: str,
    document_id: str,
    document_type: str,
    gcs_key: str = "",
    filename: str = "",
    **kwargs: Any,
) -> dict[str, Any]:
    """LLM-based structured extraction for one promoted document.

    Reads extracted text, calls Groq for typed JSON fields, and returns
    them **without writing to the database**. Stage 4–7
    (``document_verify``) handles verification, escalation, vendor
    resolution, and idempotent upsert.

    Args:
        tenant_id: Owning tenant.
        document_id: Documents row id (string).
        document_type: invoice / purchase_order / contract / amendment.
        gcs_key: GCS object key (artifact or source).
        filename: Original filename.
        **kwargs: Ignored extras.

    Returns:
        Dict with extracted fields, document_id, and status.
    """
    if document_type not in _EXTRACTABLE_TYPES:
        logger.info(
            "structured_extract_skipped",
            tenant_id=tenant_id,
            document_id=document_id,
            document_type=document_type,
        )
        return {
            "tenant_id": tenant_id,
            "document_id": document_id,
            "status": "skipped",
            "reason": f"non-extractable type: {document_type}",
        }

    engine = get_sync_engine()
    with Session(engine) as session:
        try:
            doc_key = uuid.UUID(document_id)
        except ValueError:
            logger.warning("structured_extract_bad_id", document_id=document_id)
            return {"document_id": document_id, "status": "failed", "error": "bad id"}

        doc = session.get(DocumentRow, doc_key)
        if doc is None:
            logger.warning("structured_extract_not_found", document_id=document_id)
            return {"document_id": document_id, "status": "failed", "error": "not found"}

        # Read text: prefer artifact text_snippet, fall back to GCS artifact.
        from zellovest_shared.db.models import ExtractionArtifact

        artifact = session.execute(
            select(ExtractionArtifact).where(
                ExtractionArtifact.upload_id == doc.upload_id
            )
        ).scalar_one_or_none()
        text = artifact.text_snippet if artifact is not None else ""
        if not text and gcs_key:
            text = _download_full_text(gcs_key)

        if not text:
            logger.warning(
                "structured_extract_no_text",
                tenant_id=tenant_id,
                document_id=document_id,
            )
            doc.status = "review_needed"
            session.commit()
            return {
                "tenant_id": tenant_id,
                "document_id": document_id,
                "status": "review_needed",
                "error": "no extracted text available",
            }

        # LLM extraction — raw fields only, no DB writes.
        prompt_fn = _PROMPTS[document_type]
        try:
            data = _call_llm(prompt_fn(text, filename or doc.filename))
        except StructuredExtractError as exc:
            logger.warning(
                "structured_extract_llm_failed",
                tenant_id=tenant_id,
                document_id=document_id,
                error_class="StructuredExtractError",
                error=str(exc),
            )
            doc.status = "review_needed"
            session.commit()
            return {
                "tenant_id": tenant_id,
                "document_id": document_id,
                "status": "review_needed",
                "error": str(exc),
            }

        logger.info(
            "structured_extracted_raw",
            tenant_id=tenant_id,
            document_id=document_id,
            document_type=document_type,
            vendor_name=data.get("vendor_name"),
            line_items=len(data.get("line_items", [])),
        )
        # Chain Stage 4–7: verify → escalation gate → vendor resolution → upsert.
        from zellovest_workers.tasks.document_verify import verify_and_upsert

        verify_result = verify_and_upsert.delay(
            tenant_id=tenant_id,
            document_id=document_id,
            document_type=document_type,
            extracted_data=data,
            gcs_key=gcs_key or doc.gcs_key,
            filename=filename or doc.filename,
        )
        return {
            "tenant_id": tenant_id,
            "document_id": document_id,
            "document_type": document_type,
            "data": data,
            "status": "extracted_raw",
            "gcs_key": gcs_key or doc.gcs_key,
            "filename": filename or doc.filename,
            "verification_task_id": str(verify_result.id),
        }
