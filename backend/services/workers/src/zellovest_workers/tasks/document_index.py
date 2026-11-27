"""Asynchronous indexing of extracted document passages into Qdrant."""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any

from celery import Task
from sqlalchemy.orm import Session
from zellovest_shared.db.models import Document as DocumentRow
from zellovest_shared.db.models import Upload as UploadRow
from zellovest_shared.db.models import UploadStatus as DbUploadStatus
from zellovest_shared.db.session import get_sync_engine
from zellovest_shared.logging_conf import get_logger
from zellovest_shared.rag import VoyageRateLimitError, index_document
from zellovest_shared.workers.gcs_client import GcsStorageReader

from zellovest_workers.celery_app import QUEUE_DOCUMENTS, celery_app

logger = get_logger(__name__)


def document_source_version(document: Any, artifact: Any, vendor_name: str | None) -> str:
    """Fingerprint index-relevant database metadata for backfill reconciliation."""
    values = {
        "document_id": str(document.id), "tenant_id": document.tenant_id,
        "vendor_id": str(document.vendor_id) if document.vendor_id else None,
        "vendor_name": vendor_name, "filename": document.filename,
        "document_type": str(getattr(document.document_type, "value", document.document_type)),
        "created_at": str(document.created_at), "document_updated_at": str(document.updated_at),
        "artifact_key": artifact.artifact_gcs_key, "artifact_updated_at": str(artifact.updated_at),
        "pipeline_version": 3,
    }
    return hashlib.sha256(json.dumps(values, sort_keys=True).encode("utf-8")).hexdigest()


class _DocumentIndexTask(Task):
    """Set the upload lease to failed when all Qdrant retries are exhausted."""

    def on_failure(
        self,
        exc: Exception,
        task_id: str,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
        einfo: Any,
    ) -> None:
        """Expose a terminal indexing error through the existing upload status API."""
        tenant_id = kwargs.get("tenant_id") or (args[0] if args else None)
        document_id = kwargs.get("document_id") or (args[1] if len(args) > 1 else None)
        target_collection = kwargs.get("collection") or (args[2] if len(args) > 2 else None)
        if target_collection:
            logger.error("rag_backfill_document_failed", tenant_id=tenant_id,
                         document_id=str(document_id), error_class=type(exc).__name__)
            return
        if not tenant_id or not document_id:
            return
        try:
            document_uuid = uuid.UUID(str(document_id))
            with Session(get_sync_engine()) as session:
                document = session.get(DocumentRow, document_uuid)
                if (
                    document is None
                    or document.tenant_id != tenant_id
                    or document.upload_id is None
                ):
                    return
                upload = session.get(UploadRow, document.upload_id)
                if upload is not None and upload.tenant_id == tenant_id:
                    if upload.status != DbUploadStatus.COMPLETED:
                        upload.status = DbUploadStatus.FAILED
                        upload.error = f"RAG indexing failed ({type(exc).__name__})"
                        session.commit()
        except Exception as status_error:
            logger.error(
                "rag_index_failure_status_update_failed",
                tenant_id=tenant_id,
                document_id=str(document_id),
                error_class=type(status_error).__name__,
            )
        logger.error(
            "rag_index_task_failed",
            tenant_id=tenant_id,
            document_id=str(document_id),
            task_id=task_id,
            error_class=type(exc).__name__,
        )


@celery_app.task(
    name="zellovest.workers.tasks.document_index.index_document",
    queue=QUEUE_DOCUMENTS,
    base=_DocumentIndexTask,
    bind=True,
    max_retries=4,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_jitter=True,
)
def index_document_task(
    self: Task, tenant_id: str, document_id: str, collection: str | None = None,
) -> dict[str, Any]:
    """Index extracted passages for any uploaded document, retrying failures."""
    try:
        doc_uuid = uuid.UUID(document_id)
    except ValueError as exc:
        raise ValueError("document_id must be a UUID") from exc

    with Session(get_sync_engine()) as session:
        document = session.get(DocumentRow, doc_uuid)
        if document is None or document.tenant_id != tenant_id:
            logger.warning(
                "rag_index_document_missing",
                tenant_id=tenant_id,
                document_id=document_id,
            )
            return {"status": "skipped", "reason": "document not found"}
        upload_id = document.upload_id
        vendor_id = str(document.vendor_id) if document.vendor_id else None
        filename = document.filename
        doc_type = str(getattr(document.document_type, "value", document.document_type))
        if upload_id is None:
            return {"status": "skipped", "reason": "document has no extraction artifact"}
        upload_check = session.get(UploadRow, upload_id)
        if upload_check is not None and upload_check.status == DbUploadStatus.FAILED:
            logger.info("rag_index_skip_failed", upload_id=str(upload_id))
            return {"status": "skipped", "reason": "upload already marked failed"}
        # Lock the same row that deletion and concurrent document updates modify.
        # Hold the transaction until Qdrant publication finishes; otherwise a
        # late worker could resurrect a document deleted during embedding.
        document = session.get(DocumentRow, doc_uuid, with_for_update=True, populate_existing=True)
        if document is None or document.tenant_id != tenant_id:
            return {"status": "skipped", "reason": "document not found"}
        upload_id = document.upload_id
        if upload_id is None:
            return {"status": "skipped", "reason": "document has no extraction artifact"}
        upload_check = session.get(UploadRow, upload_id, populate_existing=True)
        if upload_check is not None and upload_check.status == DbUploadStatus.FAILED:
            return {"status": "skipped", "reason": "upload already marked failed"}
        vendor_id = str(document.vendor_id) if document.vendor_id else None
        filename = document.filename
        doc_type = str(getattr(document.document_type, "value", document.document_type))
        from zellovest_shared.db.core import Vendor
        from zellovest_shared.db.models import ExtractionArtifact

        artifact_row = session.query(ExtractionArtifact).filter_by(
            tenant_id=tenant_id, upload_id=upload_id
        ).with_for_update().one_or_none()
        artifact_key = artifact_row.artifact_gcs_key if artifact_row else None
        if not artifact_key:
            raise RuntimeError("document extraction artifact is not available")
        vendor = session.get(Vendor, document.vendor_id) if document.vendor_id else None
        vendor_name = vendor.name if vendor is not None and vendor.tenant_id == tenant_id else None
        source_version = document_source_version(document, artifact_row, vendor_name)
        from zellovest_shared.config import get_settings

        settings = get_settings()
        payload_bytes = GcsStorageReader().download_bytes(
            bucket=settings.gcs_raw_bucket, key=artifact_key
        )
        if not payload_bytes:
            raise RuntimeError("extraction artifact could not be read from object storage")
        artifact = json.loads(payload_bytes.decode("utf-8"))
        try:
            count = index_document(
                tenant_id=tenant_id, document_id=document_id, vendor_id=vendor_id,
                vendor_name=vendor_name, document_type=doc_type, filename=filename,
                created_at=document.created_at, source_version=source_version,
                artifact=artifact, collection=collection,
            )
        except VoyageRateLimitError as exc:
            raise self.retry(exc=exc, countdown=exc.retry_after_seconds) from exc
        if collection is None and upload_check is not None and upload_check.tenant_id == tenant_id:
            if upload_check.status != DbUploadStatus.FAILED:
                upload_check.status = DbUploadStatus.COMPLETED
                upload_check.error = None
        session.commit()
    logger.info(
        "rag_index_task_completed",
        tenant_id=tenant_id,
        document_id=document_id,
        passage_count=count,
    )
    return {"status": "indexed", "document_id": document_id, "passages": count}
