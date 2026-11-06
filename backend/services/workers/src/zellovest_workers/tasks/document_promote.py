"""Stage 3a — Promotion: uploads row → documents table.

When Stage-2 classification completes for any supported type, this task
promotes the
``uploads`` lease row into a ``documents`` row — the business record that the
RAG index and downstream services operate on.

The promotion is a thin metadata copy: the document row stores the GCS key,
filename, classified type, page count, and classifier confidence. Vendor
resolution and structured field extraction happen in the next stage
(``document_structured_extract``) because those need LLM parsing of the
extracted text.

Execution model: ``document_classify.classify_upload`` chains this task after
classification completes. Promotion failure degrades to
``REVIEW_NEEDED`` on the upload row — it never blocks the pipeline.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from zellovest_shared.db.models import Upload as UploadRow
from zellovest_shared.db.session import get_sync_engine
from zellovest_shared.logging_conf import get_logger
from zellovest_workers.celery_app import QUEUE_DOCUMENTS, celery_app

logger = get_logger(__name__)

# Every supported type gets a canonical document row and RAG index entry.
PROMOTABLE_TYPES = frozenset(
    {"invoice", "purchase_order", "contract", "amendment", "policy", "other"}
)
# Only these types have the current structured extraction schemas.
STRUCTURED_EXTRACTION_TYPES = frozenset(
    {"invoice", "purchase_order", "contract", "amendment"}
)


def _should_promote(document_type: str | None) -> bool:
    """Return True when the classified type justifies a ``documents`` row."""
    return document_type in PROMOTABLE_TYPES


def _resolve_mime_type(source_gcs_key: str) -> str:
    """Best-effort MIME type from the stored artifact metadata."""
    return "application/octet-stream"


@celery_app.task(
    name="zellovest.workers.tasks.document_promote.promote_document",
    queue=QUEUE_DOCUMENTS,
    max_retries=3,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_jitter=True,
)
def promote_document(
    tenant_id: str,
    upload_id: str,
    document_type: str,
    filename: str = "",
    gcs_key: str = "",
    page_count: int | None = None,
    classifier_confidence: float | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Promote a classified upload into the ``documents`` table.

    Args:
        tenant_id: Owning tenant.
        upload_id: Upload row id (string).
        document_type: Classified type from the supported document type set.
        filename: Original filename.
        gcs_key: Bronze-lake GCS object key.
        page_count: Page count from extraction (optional).
        classifier_confidence: Jev confidence (optional).
        **kwargs: Ignored extras.

    Returns:
        Dict with document id and queued indexing/structured-extraction task ids.
    """
    if not _should_promote(document_type):
        logger.info(
            "document_promotion_skipped",
            tenant_id=tenant_id,
            upload_id=upload_id,
            document_type=document_type,
        )
        return {
            "tenant_id": tenant_id,
            "upload_id": upload_id,
            "status": "skipped",
            "reason": f"non-promotable type: {document_type}",
        }

    engine = get_sync_engine()
    with Session(engine) as session:
        try:
            key = uuid.UUID(upload_id)
        except ValueError:
            logger.warning("document_promote_bad_id", upload_id=upload_id)
            return {"upload_id": upload_id, "status": "failed", "error": "bad id"}

        upload = session.get(UploadRow, key)
        if upload is None or upload.tenant_id != tenant_id:
            logger.warning("document_promote_not_found", upload_id=upload_id)
            return {"upload_id": upload_id, "status": "failed", "error": "not found"}

        # Reuse existing rows so a retry can safely enqueue a lost index event.
        from zellovest_shared.db.models import Document as DocumentRow

        existing = session.execute(
            select(DocumentRow).where(DocumentRow.upload_id == key)
        ).scalar_one_or_none()
        if existing is not None and existing.tenant_id != tenant_id:
            logger.warning("document_promote_tenant_mismatch", upload_id=upload_id)
            return {"upload_id": upload_id, "status": "failed", "error": "tenant mismatch"}

        is_new_document = existing is None
        if existing is not None:
            logger.info(
                "document_promote_idempotent",
                tenant_id=tenant_id,
                upload_id=upload_id,
                document_id=str(existing.id),
            )
            document = existing
        else:
            vendor_id = None
            if upload.vendor_id:
                try:
                    candidate_vendor_id = uuid.UUID(upload.vendor_id)
                except ValueError:
                    candidate_vendor_id = None
                if candidate_vendor_id is not None:
                    from zellovest_shared.db.core import Vendor as VendorRow

                    vendor = session.get(VendorRow, candidate_vendor_id)
                    if vendor is not None and vendor.tenant_id == tenant_id:
                        vendor_id = candidate_vendor_id

            document = DocumentRow(
                tenant_id=tenant_id,
                upload_id=key,
                vendor_id=vendor_id,
                gcs_key=gcs_key or upload.gcs_key,
                filename=filename or upload.filename,
                document_type=document_type,
                mime_type=upload.mime_type,
                status="staged",
                classifier_confidence=classifier_confidence,
                page_count=page_count,
            )
            session.add(document)
            session.commit()
            session.refresh(document)

            logger.info(
                "document_promoted",
                tenant_id=tenant_id,
                upload_id=upload_id,
                document_id=str(document.id),
                document_type=document_type,
            )

        document_id = str(document.id)
        document_gcs_key = document.gcs_key
        document_filename = document.filename
        document_status = str(getattr(document.status, "value", document.status))

    # Index OCR/layout text for every type before optional structured
    # extraction. Indexing remains available when structured extraction asks
    # for human review or when a type has no structured schema.
    from zellovest_workers.tasks.document_index import index_document_task

    index_result = index_document_task.delay(
        tenant_id=tenant_id,
        document_id=document_id,
    )
    logger.info(
        "rag_index_enqueued",
        tenant_id=tenant_id,
        document_id=document_id,
        document_type=document_type,
        task_id=str(index_result.id),
    )

    extraction_task_id = None
    if document_status == "staged" and document_type in STRUCTURED_EXTRACTION_TYPES:
        from zellovest_workers.tasks.document_structured_extract import extract_structured

        extract_result = extract_structured.delay(
            tenant_id=tenant_id,
            document_id=document_id,
            document_type=document_type,
            gcs_key=document_gcs_key,
            filename=document_filename,
        )
        extraction_task_id = str(extract_result.id)

    return {
        "tenant_id": tenant_id,
        "upload_id": upload_id,
        "document_id": document_id,
        "document_type": document_type,
        "status": "promoted" if is_new_document else "already_promoted",
        "indexing_task_id": str(index_result.id),
        "extraction_task_id": extraction_task_id,
    }
