"""Asynchronous indexing of extracted document passages into Qdrant."""

from __future__ import annotations

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
from zellovest_shared.rag import index_document
from zellovest_shared.workers.gcs_client import GcsStorageReader
from zellovest_workers.celery_app import QUEUE_DOCUMENTS, celery_app

logger = get_logger(__name__)


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
    max_retries=4,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_jitter=True,
)
def index_document_task(tenant_id: str, document_id: str) -> dict[str, Any]:
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
        from zellovest_shared.db.models import ExtractionArtifact

        artifact_row = session.query(ExtractionArtifact).filter_by(
            tenant_id=tenant_id, upload_id=upload_id
        ).one_or_none()
        artifact_key = artifact_row.artifact_gcs_key if artifact_row else None
        if not artifact_key:
            raise RuntimeError("document extraction artifact is not available")

    from zellovest_shared.config import get_settings

    settings = get_settings()
    payload_bytes = GcsStorageReader().download_bytes(
        bucket=settings.gcs_raw_bucket, key=artifact_key
    )
    if not payload_bytes:
        raise RuntimeError("extraction artifact could not be read from object storage")
    artifact = json.loads(payload_bytes.decode("utf-8"))
    count = index_document(
        tenant_id=tenant_id,
        document_id=document_id,
        vendor_id=vendor_id,
        document_type=doc_type,
        filename=filename,
        artifact=artifact,
    )
    if upload_id is not None:
        with Session(get_sync_engine()) as session:
            upload = session.get(UploadRow, upload_id)
            if upload is not None and upload.tenant_id == tenant_id:
                upload.status = DbUploadStatus.COMPLETED
                upload.error = None
                session.commit()
    logger.info(
        "rag_index_task_completed",
        tenant_id=tenant_id,
        document_id=document_id,
        passage_count=count,
    )
    return {"status": "indexed", "document_id": document_id, "passages": count}
