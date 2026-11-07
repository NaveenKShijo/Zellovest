"""Worker 4: Document OCR & Extraction (Celery / GPU pods).

Pipeline (per PRD 5-7):

1. Triage: content-based format ID (magic bytes) + digital-vs-scanned
   check for PDFs (PyMuPDF text coverage).
2. Extract: digital PDFs -> PyMuPDF text/layout + PDFPlumber tables;
   scanned PDFs / TIFF / PNG -> Google Cloud Document AI OCR.
3. Classify: keyword-based inline (fallback) -> Stage-2 Jev refinement
   (``document_classify.classify_upload`` via OpenRouter).
4. Map to common schema + provenance tagging (page, bbox, confidence,
   extraction_method) per PRD §8; persist the extraction artifact
   (GCS payload + ``extraction_artifacts`` metadata row, PRD §27.5.4).

``stage_document`` (queue ``ingestion_tasks``) is the entrypoint fanned
out to by ``POST /uploads/{id}/complete``: it flips the lease row
``staged -> processing`` and enqueues ``process_document`` (queue
``document_tasks``). It implements deterministic extraction and provenance;
Stage-2 classification promotes each upload and queues Qdrant indexing.
Structured extraction remains specific to invoices and commercial agreements.
"""

import json
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from zellovest_shared.db.models import ExtractionArtifact
from zellovest_shared.db.models import Upload as UploadRow
from zellovest_shared.db.models import UploadStatus as DbUploadStatus
from zellovest_shared.db.session import get_sync_engine
from zellovest_shared.logging_conf import get_logger
from zellovest_shared.workers.gcs_client import GcsStorageReader
from zellovest_shared.workers.gcs_writer import write_bytes
from zellovest_workers.celery_app import QUEUE_DOCUMENTS, QUEUE_INGESTION, celery_app
from zellovest_workers.tasks.document_classify import (
    CLASSIFICATION_SNIPPET_CHARS,
    classify_upload,
)
from zellovest_workers.tasks.document_extract import (
    ExtractionResult,
    extract_document,
)
from zellovest_workers.tasks.document_triage import (
    TriageResult,
    triage_document_from_bytes,
)

logger = get_logger(__name__)

_CLASSIFIER_KEYWORDS: dict[str, tuple[str, ...]] = {
    "invoice": ("invoice", "inv-", "amount due", "billed", "line total"),
    "purchase_order": ("purchase order", "po number", "ship to", "requisition"),
    "contract": ("agreement", "msa", "terms and conditions", "counterparty", "renewal"),
    "amendment": ("amendment", "addendum", "contract variation"),
    "policy": ("policy", "policies", "security standard", "acceptable use"),
}


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
        if hint in (*_CLASSIFIER_KEYWORDS, "other"):
            return hint, 0.5
        return "other", 0.4
    if hint == best_type:
        return best_type, 0.9
    return best_type, 0.7


def _get_bucket() -> str:
    """Resolve the GCS raw bucket from shared settings."""
    from zellovest_shared.config import get_settings

    return get_settings().gcs_raw_bucket


def _download_blob(bucket: str, gcs_key: str) -> bytes | None:
    """Download object bytes from GCS (module seam for tests to monkeypatch)."""
    return GcsStorageReader().download_bytes(bucket=bucket, key=gcs_key)


def _build_provenance(
    *,
    field: str,
    value: str,
    confidence: float,
    source_document: str,
    extraction_method: str,
    page: int = 0,
    bounding_box: list[float] | None = None,
    triage: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a PRD §8 provenance dict for one extracted field."""
    return {
        "field": field,
        "value": value,
        "confidence": confidence,
        "source_document": source_document,
        "page": page,
        "bounding_box": bounding_box or [],
        "extraction_method": extraction_method,
        "extracted_at": datetime.now(UTC).isoformat(),
        "triage": triage,
    }


def _pages_payload(pages: list[Any]) -> list[dict[str, Any]]:
    """Convert per-page extraction dataclasses to plain dicts.

    Args:
        pages: ``PageExtraction`` instances (or already-dict pages).

    Returns:
        JSON-serializable page payloads (text blocks, tables, images).
    """
    payload: list[dict[str, Any]] = []
    for p in pages:
        payload.append(
            {
                "page_number": p.page_number,
                "text": p.text,
                "text_blocks": [
                    {"text": tb.text, "bbox": tb.bbox, "confidence": tb.confidence}
                    for tb in p.text_blocks
                ],
                "tables": [{"data": t.data, "bbox": t.bbox} for t in p.tables],
                "images": [{"bbox": i.bbox, "xref": i.xref} for i in p.images],
            }
        )
    return payload


def _build_artifact_payload(
    *,
    tenant_id: str,
    upload_id: str | None,
    source_gcs_key: str,
    filename: str,
    triage_result: Any,
    extraction_result: Any,
    doc_type: str,
    classification_confidence: float,
    provenance: dict[str, Any],
    entity_provenance: list[dict[str, Any]],
) -> dict[str, Any]:
    """Assemble the GCS extraction artifact payload (PRD §27.5.4).

    Args:
        tenant_id: Owning tenant.
        upload_id: Lease row id (None for orphan runs).
        source_gcs_key: Bronze-lake source object key.
        filename: Original filename.
        triage_result: Phase-1 triage output.
        extraction_result: Phase-2 extraction output.
        doc_type: Keyword-classified document type (preliminary).
        classification_confidence: Keyword classification confidence.
        provenance: Merged PRD §8 provenance dict.
        entity_provenance: Per-entity provenance entries.

    Returns:
        JSON-serializable artifact dict.
    """
    return {
        "schema_version": 1,
        "tenant_id": tenant_id,
        "upload_id": upload_id,
        "source_gcs_key": source_gcs_key,
        "filename": filename,
        "triage": {
            "file_type": triage_result.file_type,
            "route": triage_result.route,
            "confidence": triage_result.confidence,
            "detection_method": triage_result.detection_method,
            "has_images": triage_result.has_images,
        },
        "extraction": {
            "route": extraction_result.route,
            "file_type": extraction_result.file_type,
            "extraction_method": extraction_result.extraction_method,
            "extraction_confidence": extraction_result.confidence,
            "full_text": extraction_result.full_text,
            "pages": _pages_payload(extraction_result.pages),
            "entities": extraction_result.entities,
            "tables": extraction_result.tables,
        },
        "classification": {
            "document_type": doc_type,
            "confidence": classification_confidence,
            "method": "keyword",
            "note": "Preliminary; superseded by Stage-2 Jev classification",
        },
        "provenance": provenance,
        "entity_provenance": entity_provenance,
        "created_at": datetime.now(UTC).isoformat(),
    }


def _persist_extraction_artifact(
    *,
    tenant_id: str,
    upload_id: str | None,
    source_gcs_key: str,
    payload: dict[str, Any],
    text_snippet: str,
) -> str | None:
    """Persist the full GCS artifact and its queryable artifact row.

    Writes ``artifacts/{tenant}/{upload}/extraction.json`` (full payload)
    and upserts the ``extraction_artifacts`` row with queryable metadata
    plus the classification working-set snippet. This artifact is required
    for the RAG indexing task to complete.

    Args:
        tenant_id: Owning tenant.
        upload_id: Lease row id (persistence skipped when None).
        source_gcs_key: Bronze-lake source object key.
        payload: Artifact payload (see ``_build_artifact_payload``).
        text_snippet: First ~4k chars of extracted text (Jev input).

    Returns:
        The artifact GCS key when written, else ``None``.
    """
    if not upload_id:
        return None
    artifact_key = f"artifacts/{tenant_id}/{upload_id}/extraction.json"
    bucket = _get_bucket()
    try:
        write_bytes(
            json.dumps(payload, default=str).encode("utf-8"),
            bucket=bucket,
            key=artifact_key,
            content_type="application/json",
        )
    except Exception as exc:
        logger.error(
            "extraction_artifact_write_failed",
            tenant_id=tenant_id,
            artifact_key=artifact_key,
            error_class=type(exc).__name__,
        )
        return None
    try:
        engine = get_sync_engine()
        with Session(engine) as session:
            try:
                key = uuid.UUID(upload_id)
            except ValueError:
                return None
            row = session.execute(
                select(ExtractionArtifact).where(
                    ExtractionArtifact.upload_id == key
                )
            ).scalar_one_or_none()
            if row is None:
                row = ExtractionArtifact(
                    tenant_id=tenant_id,
                    upload_id=key,
                )
                session.add(row)
            row.source_gcs_key = source_gcs_key
            row.artifact_gcs_key = artifact_key
            row.route = payload["triage"]["route"]
            row.file_type = payload["triage"]["file_type"]
            row.text_chars = len(payload["extraction"]["full_text"])
            row.extraction_method = payload["extraction"]["extraction_method"]
            row.extraction_confidence = round(
                min(max(payload["extraction"]["extraction_confidence"], 0.0), 1.0), 4
            )
            row.text_snippet = text_snippet

            text_chars = len(payload["extraction"]["full_text"])
            session.commit()

        logger.info(
            "extraction_artifact_persisted",
            tenant_id=tenant_id,
            upload_id=upload_id,
            artifact_key=artifact_key,
            text_chars=text_chars
        )
        return artifact_key
    except Exception as exc:
        logger.error(
            "extraction_artifact_persist_failed",
            tenant_id=tenant_id,
            upload_id=upload_id,
            error_class=type(exc).__name__,
        )
        return None


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
    """Download, triage, extract, classify, and ledger-book one staged document.

    Pipeline per PRD 5-7:

    1. Download raw bytes from the GCS bronze bucket.
    2. Triage: magic-byte format ID + PyMuPDF text-coverage check for PDFs.
    3. Extract: PyMuPDF/PDFPlumber for digital PDFs; Document AI OCR for
       scanned PDFs, TIFF, and PNG.
    4. Classify: keyword-based document type (invoice / PO / contract / other).
    5. Persist provenance and queue vector indexing. The lease completes
       after the Qdrant indexing task finishes.

    Stage-2 classification queues Qdrant indexing independently from
    optional structured extraction.

    Args:
        tenant_id: Owning tenant.
        gcs_key: Verified object key.
        document_type_hint: Uploader-supplied type hint.
        upload_id: Lease row id (bookkeeping skipped when None).
        **kwargs: Backward compat (early callers passed ``s3_key``).

    Returns:
        Dict with route, extraction result, classification, provenance, and status.
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
            "file_type": "unknown",
            "status": "failed",
            "error": "blob absent",
        }

    filename = gcs_key.rsplit("/", 1)[-1]

    # Phase 1: content-based triage on the downloaded bytes.
    triage_result: TriageResult = triage_document_from_bytes(data)

    route = triage_result.route
    file_type = triage_result.file_type

    # Phase 2: data extraction based on the triage route.
    extraction_result: ExtractionResult = extract_document(
        data=data,
        file_type=file_type,
        route=route,
    )

    if extraction_result.error:
        _mark_upload(upload_id, DbUploadStatus.FAILED, extraction_result.error)
        logger.warning(
            "document_extraction_failed",
            tenant_id=tenant_id,
            gcs_key=gcs_key,
            route=route,
            file_type=file_type,
            error=extraction_result.error,
        )
        return {
            "tenant_id": tenant_id,
            "gcs_key": gcs_key,
            "upload_id": upload_id,
            "route": route,
            "file_type": file_type,
            "status": "failed",
            "error": extraction_result.error,
        }

    # Phase 3: classify the extracted text into a document type.
    text = extraction_result.full_text
    doc_type, classification_confidence = classify_document(
        text, hint=document_type_hint, filename=filename
    )

    # Phase 4: merge triage + extraction provenance (PRD §8 auditable trail).
    provenance = _build_provenance(
        field="document_type",
        value=doc_type,
        confidence=classification_confidence,
        source_document=filename,
        extraction_method=route,
        page=0,
        triage={
            "field": "document_format",
            "value": file_type,
            "confidence": triage_result.confidence,
            "source_document": filename,
            "extraction_method": triage_result.detection_method,
            "extracted_at": datetime.now(UTC).isoformat(),
        },
    )

    # Add per-entity provenance entries from extraction.
    entity_provenance = extraction_result.to_provenance_entries(
        source_document=filename,
        extraction_method=extraction_result.extraction_method,
    )

    logger.info(
        "document_extracted",
        tenant_id=tenant_id,
        gcs_key=gcs_key,
        route=route,
        file_type=file_type,
        doc_type=doc_type,
        classification_confidence=classification_confidence,
        extraction_confidence=extraction_result.confidence,
        page_count=len(extraction_result.pages),
        entity_count=len(extraction_result.entities),
        table_count=len(extraction_result.tables),
    )

    # Phase 5: persist the extraction artifact (PRD §27.5.4): full payload
    # to GCS and persist metadata plus the Stage-2 snippet to Postgres.
    artifact_gcs_key = _persist_extraction_artifact(
        tenant_id=tenant_id,
        upload_id=upload_id,
        source_gcs_key=gcs_key,
        payload=_build_artifact_payload(
            tenant_id=tenant_id,
            upload_id=upload_id,
            source_gcs_key=gcs_key,
            filename=filename,
            triage_result=triage_result,
            extraction_result=extraction_result,
            doc_type=doc_type,
            classification_confidence=classification_confidence,
            provenance=provenance,
            entity_provenance=entity_provenance,
        ),
        text_snippet=text[:CLASSIFICATION_SNIPPET_CHARS],
    )

    if upload_id and artifact_gcs_key is None:
        error = "extraction artifact could not be persisted"
        _mark_upload(upload_id, DbUploadStatus.FAILED, error)
        return {
            "tenant_id": tenant_id,
            "gcs_key": gcs_key,
            "upload_id": upload_id,
            "route": route,
            "file_type": file_type,
            "status": "failed",
            "error": error,
        }

    # Stage 2: refine classification via Jev on a dedicated task so OCR
    # success never depends on the classifier being available.
    classification_task_id = None
    if upload_id:
        try:
            classify_result = classify_upload.delay(
                tenant_id=tenant_id,
                upload_id=upload_id,
                filename=filename,
                hint=document_type_hint,
            )
            classification_task_id = str(classify_result.id)
        except Exception as exc:
            error = "document classification could not be queued"
            _mark_upload(upload_id, DbUploadStatus.FAILED, error)
            logger.error(
                "document_classification_enqueue_failed",
                tenant_id=tenant_id,
                upload_id=upload_id,
                error_class=type(exc).__name__,
            )
            return {
                "tenant_id": tenant_id,
                "gcs_key": gcs_key,
                "upload_id": upload_id,
                "route": route,
                "file_type": file_type,
                "status": "failed",
                "error": error,
            }

    return {
        "tenant_id": tenant_id,
        "gcs_key": gcs_key,
        "upload_id": upload_id,
        "route": route,
        "file_type": file_type,
        "confidence": classification_confidence,
        "detection_method": triage_result.detection_method,
        "extraction_method": extraction_result.extraction_method,
        "extraction_confidence": extraction_result.confidence,
        "document_type": doc_type,
        "provenance": provenance,
        "entity_provenance": entity_provenance,
        "page_count": len(extraction_result.pages),
        "pages": _pages_payload(extraction_result.pages),
        "entities": extraction_result.entities,
        "tables": extraction_result.tables,
        "full_text": extraction_result.full_text,
        "text_chars": len(text),
        "has_images": triage_result.has_images,
        "artifact_gcs_key": artifact_gcs_key,
        "classification_task_id": classification_task_id,
        "status": "indexing",
        "note": "Qdrant indexing is queued after Stage-2 classification.",
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
