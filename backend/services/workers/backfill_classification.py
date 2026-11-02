"""One-off admin script: re-drive Stage-2 classification for existing uploads.

Covers two gaps:

1. ``extraction_artifacts`` rows whose ``classification`` JSON is still empty
   (produced before the Stage-2 apply fix landed) -> re-enqueue
   ``classify_upload``. The task re-reads its ``text_snippet`` from
   Postgres — no GCS download, no re-extraction.
2. Uploads processed by an older build that have no artifact row at all
   -> re-enqueue ``process_document`` (re-download + re-extract + persist
   + auto-chain classification).

Usage (from ``backend/services/workers``)::

    uv run python backfill_classification.py
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from zellovest_shared.db.models import ExtractionArtifact
from zellovest_shared.db.models import Upload as UploadRow
from zellovest_shared.db.models import UploadStatus
from zellovest_shared.db.session import get_sync_engine
from zellovest_shared.logging_conf import configure_logging, get_logger
from zellovest_workers.tasks.document_classify import classify_upload
from zellovest_workers.tasks.document_ocr import process_document

configure_logging()
logger = get_logger(__name__)

_REPROCESSABLE = (UploadStatus.COMPLETED, UploadStatus.FAILED)


def main() -> None:
    """Enqueue classification/re-extraction for unclassified uploads."""
    engine = get_sync_engine()
    with Session(engine) as session:
        artifacts = session.execute(select(ExtractionArtifact)).scalars().all()
        orphans = session.execute(
            select(UploadRow)
            .outerjoin(ExtractionArtifact, ExtractionArtifact.upload_id == UploadRow.id)
            .where(
                ExtractionArtifact.id.is_(None),
                UploadRow.status.in_(_REPROCESSABLE),
            )
        ).scalars().all()

    classified = 0
    for row in artifacts:
        if row.classification:
            continue  # already classified (including keyword fallbacks)
        classify_upload.delay(
            tenant_id=row.tenant_id,
            upload_id=str(row.upload_id),
            filename=(row.source_gcs_key or "").rsplit("/", 1)[-1],
        )
        classified += 1
        logger.info(
            "classification_backfill_enqueued",
            tenant_id=row.tenant_id,
            upload_id=str(row.upload_id),
        )

    reextracted = 0
    for row in orphans:
        hint = (
            row.document_type
            if row.document_type in ("invoice", "purchase_order", "contract")
            else None
        )
        process_document.delay(
            tenant_id=row.tenant_id,
            gcs_key=row.gcs_key,
            document_type_hint=hint,
            upload_id=str(row.id),
        )
        reextracted += 1
        logger.info(
            "extraction_backfill_enqueued",
            tenant_id=row.tenant_id,
            upload_id=str(row.id),
            gcs_key=row.gcs_key,
        )

    logger.info(
        "classification_backfill_done",
        artifacts_total=len(artifacts),
        classify_enqueued=classified,
        reextract_enqueued=reextracted,
    )
    print(
        "Backfill complete: "
        f"{classified}/{len(artifacts)} classify + "
        f"{reextracted} re-extract tasks enqueued."
    )


if __name__ == "__main__":
    main()

