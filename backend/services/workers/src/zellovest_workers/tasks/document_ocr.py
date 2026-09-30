"""Worker 4: Document OCR & Extraction (Celery / GPU pods).

Pipeline (per PRD 5-7):
1. Triage: digital text PDF vs scanned/image (pdfplumber attempt first).
2. Route stable tables -> deterministic extraction; variable/scanned ->
   Document AI / OCR (Google Document AI, Textract, Azure DI).
3. Classify: invoice / purchase_order / contract / other.
4. Map to common schema + provenance tagging (page, bbox, confidence,
   extraction_method) and emit chunks + vectors for MCP-2.
"""

from typing import Any

from zellovest_shared.logging_conf import get_logger
from zellovest_workers.celery_app import QUEUE_DOCUMENTS, celery_app

logger = get_logger(__name__)


def triage_document(s3_key: str, mime_type: str = "application/pdf") -> str:
    """Decide extraction route: ``python`` (digital) or ``document_ai`` (scanned/variable)."""
    # TODO: download head of object, try pdfplumber text extraction;
    # fall back to document_ai when text coverage is low or pages are images.
    del s3_key, mime_type
    return "document_ai"


@celery_app.task(
    name="zellovest.workers.tasks.document_ocr.process_document",
    queue=QUEUE_DOCUMENTS,
    max_retries=3,
)
def process_document(
    tenant_id: str,
    s3_key: str,
    document_type_hint: str | None = None,
    upload_id: str | None = None,
) -> dict[str, Any]:
    """Process one staged document through triage -> extraction -> schema map."""
    route = triage_document(s3_key)
    logger.info(
        "document_routed",
        tenant_id=tenant_id,
        s3_key=s3_key,
        route=route,
        hint=document_type_hint,
    )
    # TODO: implement providers + classifier + schema mapper + vector embedding.
    # Must attach provenance {source_document, page, bbox, extraction_method,
    # confidence, extracted_at} per PRD 8 before writing to Vector DB.
    return {
        "tenant_id": tenant_id,
        "s3_key": s3_key,
        "upload_id": upload_id,
        "route": route,
        "status": "queued",
        "note": "OCR provider + schema mapping TODO",
    }


@celery_app.task(
    name="zellovest.workers.tasks.document_ocr.reprocess_low_confidence",
    queue=QUEUE_DOCUMENTS,
    max_retries=3,
)
def reprocess_low_confidence(tenant_id: str, document_id: str) -> dict[str, Any]:
    """Re-run extraction for low-confidence docs flagged for human review."""
    logger.info("document_reprocess", tenant_id=tenant_id, document_id=document_id)
    return {"tenant_id": tenant_id, "document_id": document_id, "status": "queued"}
