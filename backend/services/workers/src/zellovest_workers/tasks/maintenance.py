"""Maintenance tasks: expired upload-lease janitor (Celery Beat, every 15 min).

Deletes abandoned ``pending`` upload rows whose signed-URL lease expired
more than one hour ago, including best-effort removal of their orphaned
GCS blobs (PUT succeeded but ``complete`` never ran). Only ``pending``
rows are touched; staged, processing, completed, and failed rows are
never deleted by this task.

DELETE is idempotent, so Beat redelivery and task retries are safe.
"""

from typing import Any

from sqlalchemy import text

from zellovest_shared.db.session import get_sync_engine
from zellovest_shared.logging_conf import get_logger
from zellovest_shared.workers.gcs_client import GcsStorageReader
from zellovest_workers.celery_app import QUEUE_INGESTION, celery_app

logger = get_logger(__name__)

SELECT_EXPIRED_UPLOADS_SQL = (
    "SELECT gcs_key FROM uploads "
    "WHERE status = 'pending' AND expires_at < now() - INTERVAL '1 hour' "
    "LIMIT :batch_size"
)

PURGE_EXPIRED_UPLOADS_SQL = (
    "DELETE FROM uploads "
    "WHERE ctid IN ("
    "SELECT ctid FROM uploads "
    "WHERE status = 'pending' AND expires_at < now() - INTERVAL '1 hour' "
    "LIMIT :batch_size)"
)


def purge_expired_upload_rows(batch_size: int = 1000) -> dict[str, int]:
    """Delete one bounded batch of expired pending leases + orphan blobs.

    Blob cleanup is best-effort: GCS failures are logged and counted,
    never fail the purge.

    Args:
        batch_size: Maximum rows to delete in this run.

    Returns:
        Dict with deleted row count and removed orphan blob count.
    """
    from zellovest_shared.config import get_settings

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
