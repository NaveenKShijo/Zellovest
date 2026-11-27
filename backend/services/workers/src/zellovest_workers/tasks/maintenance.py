"""Maintenance tasks: expired upload-lease janitor.

Two-phase cleanup lifecycle:
1. Mark expired pending leases as ``failed`` (Celery Beat, every 1 min):
   When ``expires_at < now()``, pending leases are updated to ``status = 'failed'``
   with ``error = 'lease expired before complete'``. This ensures the UI and queries
   immediately reflect that the signed-URL has expired.
2. Purge expired leases (Celery Beat, every 15 min):
   Deletes abandoned upload leases whose signed-URL expired more than one hour ago
   (``expires_at < now() - INTERVAL '1 hour'`` and ``status IN ('pending', 'failed')``),
   including best-effort removal of their orphaned GCS blobs. Staged, processing,
   and completed rows (as well as pipeline documents where expires_at is None)
   are never touched.

DELETE is idempotent, so Beat redelivery and task retries are safe.
"""

from typing import Any

from sqlalchemy import text
from zellovest_shared.db.session import get_sync_engine
from zellovest_shared.logging_conf import get_logger
from zellovest_shared.workers.gcs_client import GcsStorageReader

from zellovest_workers.celery_app import QUEUE_INGESTION, celery_app

logger = get_logger(__name__)

MARK_EXPIRED_UPLOADS_SQL = (
    "UPDATE uploads "
    "SET status = 'failed', "
    "    error = 'lease expired before complete', "
    "    updated_at = now() "
    "WHERE status = 'pending' AND expires_at < now()"
)

SELECT_EXPIRED_UPLOADS_SQL = (
    "SELECT gcs_key FROM uploads "
    "WHERE expires_at IS NOT NULL "
    "  AND expires_at < now() - INTERVAL '1 hour' "
    "  AND status IN ('pending', 'failed') "
    "LIMIT :batch_size"
)

PURGE_EXPIRED_UPLOADS_SQL = (
    "DELETE FROM uploads "
    "WHERE ctid IN ("
    "SELECT ctid FROM uploads "
    "WHERE expires_at IS NOT NULL "
    "  AND expires_at < now() - INTERVAL '1 hour' "
    "  AND status IN ('pending', 'failed') "
    "LIMIT :batch_size)"
)


def mark_expired_upload_rows() -> int:
    """Mark any pending upload lease whose expires_at has passed as failed.

    Returns:
        Count of rows marked failed.
    """
    engine = get_sync_engine()
    with engine.begin() as conn:
        result = conn.execute(text(MARK_EXPIRED_UPLOADS_SQL))
        marked = result.rowcount or 0
    return marked


@celery_app.task(
    name="zellovest.workers.tasks.maintenance.mark_expired_uploads",
    queue=QUEUE_INGESTION,
    max_retries=3,
)
def mark_expired_uploads() -> dict[str, Any]:
    """Celery Beat entrypoint: mark expired pending uploads as failed.

    Returns:
        Dict with marked row count.
    """
    try:
        marked = mark_expired_upload_rows()
    except Exception as exc:
        logger.error(
            "uploads_mark_expired_failed",
            error_class=type(exc).__name__,
        )
        raise
    if marked > 0:
        logger.info("uploads_mark_expired_complete", marked=marked)
    return {"marked": marked}


def purge_expired_upload_rows(batch_size: int = 1000) -> dict[str, int]:
    """Delete one bounded batch of expired pending/failed leases + orphan blobs.

    Leases must have expired more than 1 hour ago.
    Blob cleanup is best-effort: GCS failures are logged and counted,
    never fail the purge.

    Args:
        batch_size: Maximum rows to delete in this run.

    Returns:
        Dict with deleted row count and removed orphan blob count.
    """
    from zellovest_shared.config import get_settings

    # Mark any newly expired leases first
    mark_expired_upload_rows()

    engine = get_sync_engine()
    with engine.begin() as conn:
        keys = [
            row[0]
            for row in conn.execute(text(SELECT_EXPIRED_UPLOADS_SQL), {"batch_size": batch_size})
        ]
        result = conn.execute(
            text(PURGE_EXPIRED_UPLOADS_SQL),
            {"batch_size": batch_size},
        )
        deleted = result.rowcount or 0
    orphans_removed = 0
    if keys:
        bucket = get_settings().gcs_raw_bucket
        reader = GcsStorageReader()
        for key in keys:
            try:
                if reader.delete_object(bucket=bucket, key=key):
                    orphans_removed += 1
            except Exception as exc:
                logger.warning(
                    "purge_orphan_delete_failed",
                    key=key,
                    error_class=type(exc).__name__,
                )
    return {"deleted": deleted, "orphans_removed": orphans_removed}


@celery_app.task(
    name="zellovest.workers.tasks.maintenance.purge_expired_uploads",
    queue=QUEUE_INGESTION,
    max_retries=3,
)
def purge_expired_uploads(batch_size: int = 1000) -> dict[str, Any]:
    """Celery Beat entrypoint: purge expired pending uploads (every 15 min).

    Args:
        batch_size: Maximum rows to delete per run.

    Returns:
        Dict with deleted row and orphan blob counts.
    """
    try:
        counts = purge_expired_upload_rows(batch_size=batch_size)
    except Exception as exc:
        logger.error(
            "uploads_purge_failed",
            error_class=type(exc).__name__,
        )
        raise
    logger.info("uploads_purge_complete", **counts, batch_size=batch_size)
    return {**counts, "batch_size": batch_size}


@celery_app.task(
    name="zellovest.workers.tasks.maintenance.purge_document_artifacts",
    queue=QUEUE_INGESTION,
    max_retries=3,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_jitter=True,
)
def purge_document_artifacts(
    tenant_id: str,
    upload_id: str,
    gcs_keys: list[str],
    structured_ids: list[str],
) -> dict[str, Any]:
    """Asynchronously purge raw/extracted GCS blobs and Qdrant RAG points.

    Offloaded from DELETE /api/v1/documents/{document_id} so the HTTP response
    returns to the user immediately rather than waiting seconds for remote storage I/O.

    Args:
        tenant_id: Owning tenant.
        upload_id: Upload lease id.
        gcs_keys: List of GCS object keys to delete.
        structured_ids: List of structured document UUID strings to purge from Qdrant.

    Returns:
        Summary dict of cleaned resources.
    """
    from zellovest_shared.config import get_settings

    settings = get_settings()
    bucket = settings.gcs_raw_bucket
    deleted_blobs = 0
    failed_blobs = 0

    if bucket and gcs_keys:
        reader = GcsStorageReader()
        for key in sorted(gcs_keys):
            try:
                if reader.delete_object(bucket=bucket, key=key):
                    deleted_blobs += 1
            except Exception as exc:
                failed_blobs += 1
                logger.warning(
                    "document_async_blob_cleanup_failed",
                    tenant_id=tenant_id,
                    upload_id=upload_id,
                    gcs_key=key,
                    error_class=type(exc).__name__,
                )

    deleted_vectors = 0
    failed_vectors = 0
    if structured_ids:
        from zellovest_shared.rag import delete_document_points

        for structured_id in structured_ids:
            try:
                delete_document_points(
                    tenant_id=tenant_id,
                    document_id=str(structured_id),
                )
                deleted_vectors += 1
            except Exception as exc:
                failed_vectors += 1
                logger.warning(
                    "document_async_vector_cleanup_failed",
                    tenant_id=tenant_id,
                    upload_id=upload_id,
                    structured_document_id=str(structured_id),
                    error_class=type(exc).__name__,
                )

    logger.info(
        "document_artifacts_purged",
        tenant_id=tenant_id,
        upload_id=upload_id,
        deleted_blobs=deleted_blobs,
        failed_blobs=failed_blobs,
        deleted_vectors=deleted_vectors,
        failed_vectors=failed_vectors,
    )
    if failed_blobs or failed_vectors:
        # The operation is idempotent: Celery can retry the whole batch safely.
        # Never report a cleanup as complete while an index still contains data.
        raise RuntimeError("document artifact cleanup incomplete; retry required")
    return {
        "status": "completed",
        "deleted_blobs": deleted_blobs,
        "failed_blobs": failed_blobs,
        "deleted_vectors": deleted_vectors,
        "failed_vectors": failed_vectors,
    }

