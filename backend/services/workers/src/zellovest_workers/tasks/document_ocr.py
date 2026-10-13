"""Worker 4: Document OCR & Extraction (Celery / GPU pods).

Pipeline (per PRD 5-7):
1. Triage: digital text PDF vs scanned/image (pdfplumber attempt first).
2. Route stable tables -> deterministic extraction; variable/scanned ->
   Google Cloud Document AI.
3. Classify: invoice / purchase_order / contract / other.
4. Map to common schema + provenance tagging (page, bbox, confidence,
   extraction_method) and emit chunks + vectors for MCP-2.

``stage_document`` (queue ``ingestion_tasks``) is the entrypoint fanned
out to by ``POST /uploads/{id}/complete``: it flips the lease row
``staged -> processing`` and enqueues ``process_document`` (queue
``document_tasks``). LLM extraction + vector embedding remain TODOs;
this module implements deterministic download/triage/classify plus
lease bookkeeping with per-field provenance stubs.
"""

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from zellovest_shared.db.models import Upload as UploadRow
from zellovest_shared.db.models import UploadStatus as DbUploadStatus
from zellovest_shared.db.session import get_sync_engine
from zellovest_shared.logging_conf import get_logger
from zellovest_shared.workers.gcs_client import GcsStorageReader
from zellovest_workers.celery_app import QUEUE_DOCUMENTS, QUEUE_INGESTION, celery_app

logger = get_logger(__name__)

_TEXT_COVERAGE_THRESHOLD = 50

_CLASSIFIER_KEYWORDS: dict[str, tuple[str, ...]] = {
    "invoice": ("invoice", "inv-", "amount due", "billed", "line total"),
    "purchase_order": ("purchase order", "po number", "ship to", "requisition"),
    "contract": ("agreement", "msa", "terms and conditions", "counterparty", "renewal"),
}


def _download_blob(bucket: str, gcs_key: str) -> bytes | None:
    """Download object bytes (module seam for tests to monkeypatch)."""
    return GcsStorageReader().download_bytes(bucket=bucket, key=gcs_key)


def triage_document(data: bytes | None, mime_type: str = "application/pdf") -> tuple[str, str]:
    """Decide extraction route and return (route, extracted_text).

    Digital PDFs with real text coverage route ``python`` (deterministic
    pdfplumber path); images, scanned PDFs, and anything unreadable route
    ``document_ai``. pdfplumber is an optional import: when unavailable
    the decision degrades to ``document_ai`` and logs it.

    Args:
        data: Downloaded object bytes (None when the blob is absent).
        mime_type: Object MIME type.

    Returns:
        Tuple of (route, extracted_text).
    """
    if not data or not mime_type.startswith(("application/pdf", "image/")):
        return "document_ai", ""
    if mime_type.startswith("image/"):
        return "document_ai", ""
    try:
        import pdfplumber
    except ImportError:
        logger.warning("pdfplumber_missing_fallback_document_ai")
        return "document_ai", ""
    try:
        import io

        text_parts: list[str] = []
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            for page in pdf.pages:
                text_parts.append(page.extract_text() or "")
        text = "\n".join(text_parts)
    except Exception as exc:
        logger.warning("pdf_triage_failed", error_class=type(exc).__name__)
        return "document_ai", ""
    if len(text.strip()) >= _TEXT_COVERAGE_THRESHOLD:
        return "python", text
    return "document_ai", text


def classify_document(text: str, hint: str | None = None, filename: str = "") -> tuple[str, float]:
    """Keyword classify extracted text into a document type.

    Args:
        text: Extracted (or empty) document text.
        hint: Uploader-supplied document_type hint.
        filename: Original filename (weak signal).

    Returns:
        Tuple of (document_type, confidence).
    """
    haystack = f"{text}\n{filename}".lower()
    best_type = "other"
    best_hits = 0
    for doc_type, keywords in _CLASSIFIER_KEYWORDS.items():
        hits = sum(1 for kw in keywords if kw in haystack)
        if hits > best_hits:
            best_type, best_hits = doc_type, hits
    if best_hits == 0:
        if hint in ("invoice", "purchase_order", "contract"):
            return hint, 0.5
        return "other", 0.4
    if hint == best_type:
        return best_type, 0.9
    return best_type, 0.7


def _get_bucket() -> str:
    """Resolve the GCS raw bucket from shared settings."""
    from zellovest_shared.config import get_settings

    return get_settings().gcs_raw_bucket


@celery_app.task(
    name="zellovest.workers.tasks.document_ocr.stage_document",
    queue=QUEUE_INGESTION,
    max_retries=3,
)
def stage_document(
    tenant_id: str,
    gcs_key: str,
    upload_id: str,
    document_type_hint: str | None = None,
) -> dict[str, Any]:
    """Flip a staged lease to processing and fan out to process_document.

    Args:
        tenant_id: Owning tenant (must match the lease row).
        gcs_key: Verified object key (from the lease row, not the client).
        upload_id: Lease row id.
        document_type_hint: Uploader-supplied type hint.

    Returns:
        Dict with upload id, staged task id, and status.
    """
    engine = get_sync_engine()
    with Session(engine) as session:
        try:
            row = session.get(UploadRow, uuid.UUID(upload_id))
        except ValueError:
            logger.warning("stage_document_bad_id", upload_id=upload_id)
            return {"upload_id": upload_id, "status": "failed", "error": "bad id"}
        if row is None or row.tenant_id != tenant_id or row.gcs_key != gcs_key:
            logger.warning("stage_document_not_found", upload_id=upload_id)
            return {"upload_id": upload_id, "status": "failed", "error": "not found"}
        if row.status != DbUploadStatus.STAGED:
            logger.info(
                "stage_document_skip",
                upload_id=upload_id,
                status=row.status.value,
            )
            return {"upload_id": upload_id, "status": row.status.value, "skipped": True}
        row.status = DbUploadStatus.PROCESSING
        session.commit()

    result = process_document.delay(
        tenant_id=tenant_id,
        gcs_key=gcs_key,
        document_type_hint=document_type_hint or row.document_type,
        upload_id=upload_id,
    )
    logger.info("document_staged", tenant_id=tenant_id, upload_id=upload_id, task_id=result.id)
    return {"upload_id": upload_id, "status": "processing", "task_id": str(result.id)}


@celery_app.task(
    name="zellovest.workers.tasks.document_ocr.process_document",
    queue=QUEUE_DOCUMENTS,
    max_retries=3,
)
def process_document(
    tenant_id: str,
    gcs_key: str,
    document_type_hint: str | None = None,
    upload_id: str | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Download, triage, classify, and ledger-book one staged document.

    LLM extraction + vector embedding remain TODOs (M3); this step
    performs the deterministic prefix and records the outcome on the
    lease row (``processing -> completed/failed``) with provenance.

    Args:
        tenant_id: Owning tenant.
        gcs_key: Verified object key.
        document_type_hint: Uploader-supplied type hint.
        upload_id: Lease row id (bookkeeping skipped when None).
        **kwargs: Backward compat (early callers passed ``s3_key``).

    Returns:
        Dict with route, classification, confidence, and status.
    """
    # Backward compat: early callers passed ``s3_key``.
    if not gcs_key:
        gcs_key = kwargs.get("s3_key", "")
    bucket = _get_bucket()
    data = _download_blob(bucket, gcs_key)
    if data is None:
        _mark_upload(upload_id, DbUploadStatus.FAILED, "blob absent from GCS")
        logger.warning("document_blob_absent", tenant_id=tenant_id, gcs_key=gcs_key)
        return {
            "tenant_id": tenant_id,
            "gcs_key": gcs_key,
            "upload_id": upload_id,
            "route": "document_ai",
            "status": "failed",
            "error": "blob absent",
        }

    route, text = triage_document(data)
    filename = gcs_key.rsplit("/", 1)[-1]
    doc_type, confidence = classify_document(text, hint=document_type_hint, filename=filename)
    provenance = {
        "field": "document_type",
        "value": doc_type,
        "confidence": confidence,
        "source_document": filename,
        "extraction_method": route,
        "extracted_at": datetime.now(UTC).isoformat(),
    }
    logger.info(
        "document_routed",
        tenant_id=tenant_id,
        gcs_key=gcs_key,
        route=route,
        doc_type=doc_type,
        confidence=confidence,
    )
    # TODO(M3): LLM/schema extraction for variable layouts + chunk embed
    # into the vector store (MCP-2). Until then the deterministic outcome
    # is ledgered and the lease completes.
    _mark_upload(upload_id, DbUploadStatus.COMPLETED, None)
    return {
        "tenant_id": tenant_id,
        "gcs_key": gcs_key,
        "upload_id": upload_id,
        "route": route,
        "document_type": doc_type,
        "provenance": provenance,
        "text_chars": len(text),
        "status": "completed",
        "note": "LLM extraction + vector embedding TODO (M3)",
    }


def _mark_upload(upload_id: str | None, status: DbUploadStatus, error: str | None) -> None:
    """Best-effort lease status update (never fails the task).

    Args:
        upload_id: Lease row id (skipped when None).
        status: Terminal status to record.
        error: Error detail for failed rows.
    """
    if not upload_id:
        return
    try:
        engine = get_sync_engine()
        with Session(engine) as session:
            try:
                row = session.get(UploadRow, uuid.UUID(upload_id))
            except ValueError:
                return
            if row is None:
                return
            row.status = status
            row.error = error
            session.commit()
    except Exception as exc:
        logger.warning("upload_mark_failed", upload_id=upload_id, error_class=type(exc).__name__)


@celery_app.task(
    name="zellovest.workers.tasks.document_ocr.reprocess_low_confidence",
    queue=QUEUE_DOCUMENTS,
    max_retries=3,
)
def reprocess_low_confidence(tenant_id: str, document_id: str) -> dict[str, Any]:
    """Re-run extraction for low-confidence docs flagged for human review."""
    logger.info("document_reprocess", tenant_id=tenant_id, document_id=document_id)
    return {"tenant_id": tenant_id, "document_id": document_id, "status": "queued"}
