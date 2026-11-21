"""Worker 6: Maverick Spend Detection Pipeline.

Per PRD 14-17 and Technical Architecture Specification:
Stage 0: Normalization & Ingestion into card_transactions.
Stage 1: Feature Engineering + Preliminary Jev AI Screening (cadence, recurrence, software).
Stage 2: Merchant & Product Context Resolution (Groq JSON + persistent cache).
Stage 3: Active contracted-software capability retrieval (dedicated Qdrant collection).
Stage 4: Final Maverick Spend Assessment (Deterministic Policy + Jev AI).
Stage 5: Alert Generation & Persistence (maverick_alerts).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from threading import Lock
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session
from zellovest_shared.config import get_settings
from zellovest_shared.db.session import get_session_factory
from zellovest_shared.db.transact import CardTransaction
from zellovest_shared.logging_conf import get_logger
from zellovest_shared.maverick.catalog_matcher import sync_active_contract_products
from zellovest_shared.maverick.pipeline import process_transaction_maverick_spend
from zellovest_shared.rag import VoyageRateLimitError
from zellovest_shared.workers.gcs_writer import list_object_keys, read_records_gz

from zellovest_workers.celery_app import QUEUE_ANALYTICS, celery_app

logger = get_logger(__name__)
_CONTRACT_INDEX_REFRESH_INTERVAL = timedelta(minutes=5)
_contract_index_refreshed_at: dict[str, datetime] = {}
_contract_index_refresh_lock = Lock()


def _refresh_contract_product_index(
    session: Session, tenant_id: str, settings: Any = None
) -> dict[str, int] | None:
    """Refresh approved software vectors without blocking spend detection.

    A vector-store or enrichment outage should not stop a card-transaction
    scan from producing the underlying Maverick alert. In that case stage 3
    records no approved alternative and the alert remains reviewable.
    """
    try:
        summary = sync_active_contract_products(session, tenant_id, settings=settings)
        logger.info("maverick_contract_product_index_refreshed", tenant_id=tenant_id, **summary)
        return summary
    except Exception as exc:
        logger.warning(
            "maverick_contract_product_index_refresh_failed",
            tenant_id=tenant_id,
            error_class=type(exc).__name__,
            error=str(exc),
        )
        return None


def _ensure_contract_product_index(session: Session, tenant_id: str) -> None:
    """Refresh active contract vectors once per worker and tenant every five minutes.

    Ramp backfills dispatch one single-transaction task per cleared card
    transaction. This guard ensures the first task has a real procurement
    catalog available while avoiding repeated Groq and embedding calls for the
    remaining transactions in the same batch.
    """
    now = datetime.now(UTC)
    with _contract_index_refresh_lock:
        refreshed_at = _contract_index_refreshed_at.get(tenant_id)
        if (
            refreshed_at is not None
            and now - refreshed_at < _CONTRACT_INDEX_REFRESH_INTERVAL
        ):
            return
        summary = _refresh_contract_product_index(session, tenant_id)
        if summary is not None:
            _contract_index_refreshed_at[tenant_id] = now


@celery_app.task(
    name="zellovest.workers.tasks.maverick_spend.detect_maverick_spend_for_transaction",
    queue=QUEUE_ANALYTICS,
    max_retries=3,
)
def detect_maverick_spend_for_transaction(
    tenant_id: str,
    transaction_id: str,
) -> dict[str, Any]:
    """Run the 5-stage Maverick Spend detection workflow on a single transaction."""
    logger.info(
        "maverick_single_detect_started",
        tenant_id=tenant_id,
        transaction_id=transaction_id,
    )
    factory = get_session_factory()
    session = factory()
    try:
        _ensure_contract_product_index(session, tenant_id)
        result = process_transaction_maverick_spend(
            session=session,
            tenant_id=tenant_id,
            transaction_id=transaction_id,
        )
        logger.info(
            "maverick_single_detect_completed",
            tenant_id=tenant_id,
            transaction_id=transaction_id,
            status=result.get("status"),
        )
        return result
    except Exception as exc:
        logger.error(
            "maverick_single_detect_failed",
            tenant_id=tenant_id,
            transaction_id=transaction_id,
            error=str(exc),
        )
        raise
    finally:
        session.close()


@celery_app.task(
    name="zellovest.workers.tasks.maverick_spend.detect_maverick_spend",
    queue=QUEUE_ANALYTICS,
    max_retries=3,
)
def detect_maverick_spend(
    tenant_id: str, lookback_days: int = 90, min_amount: float = 5.0
) -> dict[str, Any]:
    """Batch scan recent cleared card transactions for maverick spend candidates."""
    logger.info("maverick_batch_detect_started", tenant_id=tenant_id, lookback_days=lookback_days)
    factory = get_session_factory()
    session = factory()
    try:
        _refresh_contract_product_index(session, tenant_id)
        cutoff = datetime.now(UTC) - timedelta(days=lookback_days)
        stmt = (
            select(CardTransaction.id)
            .where(
                CardTransaction.tenant_id == tenant_id,
                CardTransaction.amount >= min_amount,
                CardTransaction.txn_date >= cutoff,
                CardTransaction.state == "CLEARED",
            )
            .order_by(CardTransaction.txn_date.desc())
        )
        txn_ids = list(session.execute(stmt).scalars().all())

        if not txn_ids:
            return {"tenant_id": tenant_id, "flagged": 0, "scored": 0, "status": "no_data"}

        flagged = 0
        scored = 0

        for txn_id in txn_ids:
            try:
                res = process_transaction_maverick_spend(
                    session=session,
                    tenant_id=tenant_id,
                    transaction_id=txn_id,
                )
                scored += 1
                if res.get("status") == "alert_created":
                    flagged += 1
            except Exception as item_exc:
                logger.warning(
                    "maverick_item_process_error",
                    transaction_id=str(txn_id),
                    error=str(item_exc),
                )

        logger.info(
            "maverick_batch_detect_complete", tenant_id=tenant_id, flagged=flagged, scored=scored
        )
        return {"tenant_id": tenant_id, "flagged": flagged, "scored": scored}
    finally:
        session.close()


_CARD_TXN_PREFIX = "raw/ramp_card_transactions/"


def _resolve_scan_keys(
    *,
    bucket: str,
    project: str | None,
    gcs_key: str | None,
    sync_id: str | None,
    prefix: str | None,
    lookback_days: int,
) -> list[str]:
    """Resolve which GCS bronze objects a maverick scan should read.

    Resolution order:
        1. Explicit ``gcs_key`` (single object written by a Ramp poll sync).
        2. ``sync_id`` -> every object under ``raw/ramp_card_transactions/sync=<id>/``.
        3. ``prefix`` (or the whole card-transaction prefix) limited to
           objects modified within ``lookback_days``.

    Args:
        bucket: GCS raw bucket.
        project: GCP project id (None uses default credentials).
        gcs_key: Exact object key to scan.
        sync_id: Ingestion sync ticket to scan.
        prefix: Explicit GCS prefix to scan.
        lookback_days: Recency window used only for prefix discovery.

    Returns:
        Object keys to read (newest first). Empty when nothing matches.

    Raises:
        ValueError: When neither a key nor a usable prefix can be resolved.
    """
    if gcs_key and gcs_key.strip():
        return [gcs_key.strip()]

    if sync_id and sync_id.strip():
        target_prefix = f"{_CARD_TXN_PREFIX}sync={sync_id.strip()}/"
        return list_object_keys(bucket=bucket, prefix=target_prefix, project=project)

    target_prefix = (prefix or _CARD_TXN_PREFIX).strip()
    if not target_prefix:
        raise ValueError("a gcs_key, sync_id or prefix is required to scan the bronze lake")
    modified_since = (
        datetime.now(UTC) - timedelta(days=lookback_days) if lookback_days > 0 else None
    )
    keys = list_object_keys(
        bucket=bucket,
        prefix=target_prefix,
        project=project,
        modified_since=modified_since,
    )
    if keys or modified_since is None:
        return keys

    # The UI-triggered scan must still work when the newest object predates the
    # lookback window (or when GCS omits last-modified metadata), so fall back
    # to the most recent objects under the prefix.
    logger.info(
        "maverick_scan_lookback_empty_falling_back",
        prefix=target_prefix,
        lookback_days=lookback_days,
    )
    return list_object_keys(
        bucket=bucket,
        prefix=target_prefix,
        project=project,
        max_results=25,
    )


@celery_app.task(
    name="zellovest.workers.tasks.maverick_spend.scan_maverick_spend_from_gcs",
    queue=QUEUE_ANALYTICS,
    max_retries=3,
)
def scan_maverick_spend_from_gcs(
    tenant_id: str,
    gcs_key: str | None = None,
    sync_id: str | None = None,
    prefix: str | None = None,
    lookback_days: int = 90,
    run_inline: bool = True,
) -> dict[str, Any]:
    """Scan a Ramp card-transaction object (or sync) from GCS end to end.

    Pipeline: read gzipped JSONL -> normalize/upsert ``card_transactions`` ->
    run the 5-stage maverick pipeline -> persist ``maverick_alerts``.

    Args:
        tenant_id: Tenant owning the data.
        gcs_key: Exact bronze object key (``raw/ramp_card_transactions/...``).
        sync_id: Ingestion sync ticket; scans every object in that sync.
        prefix: Alternative GCS prefix for ad-hoc backfills.
        lookback_days: Recency window when discovering by prefix.
        run_inline: When True, run detection in this task so alerts are
            committed before the task returns. When False, per-transaction
            analytics tasks are dispatched instead.

    Returns:
        Summary with promoted/cleared/flagged counts and the scraped keys.
    """
    logger.info(
        "maverick_gcs_scan_started",
        tenant_id=tenant_id,
        gcs_key=gcs_key,
        sync_id=sync_id,
        prefix=prefix,
        lookback_days=lookback_days,
        run_inline=run_inline,
    )
    settings = get_settings()
    bucket = settings.gcs_raw_bucket
    project = settings.google_cloud_project or None

    keys = _resolve_scan_keys(
        bucket=bucket,
        project=project,
        gcs_key=gcs_key,
        sync_id=sync_id,
        prefix=prefix,
        lookback_days=lookback_days,
    )
    if not keys:
        logger.warning(
            "maverick_gcs_scan_no_objects",
            tenant_id=tenant_id,
            gcs_key=gcs_key,
            sync_id=sync_id,
            prefix=prefix,
        )
        return {
            "tenant_id": tenant_id,
            "status": "no_data",
            "keys": [],
            "promoted": 0,
            "cleared": 0,
            "flagged": 0,
        }

    # Imported lazily to avoid a circular import with the ingestion tasks module.
    from zellovest_workers.tasks.ingestion import _promote_card_transaction_records

    factory = get_session_factory()
    session = factory()
    promoted = 0
    cleared_ids: list[str] = []
    failed_keys: list[str] = []
    try:
        for key in keys:
            try:
                records = read_records_gz(bucket=bucket, key=key, project=project)
            except Exception as gcs_err:
                logger.warning(
                    "maverick_gcs_batch_read_failed",
                    tenant_id=tenant_id,
                    key=key,
                    error=str(gcs_err),
                )
                failed_keys.append(key)
                continue

            promoted_count, cleared = _promote_card_transaction_records(
                session, tenant_id, key, records
            )
            promoted += promoted_count
            cleared_ids.extend(cleared)
            logger.info(
                "maverick_gcs_batch_promoted",
                tenant_id=tenant_id,
                key=key,
                records=len(records),
                promoted=promoted_count,
                cleared=len(cleared),
            )

        session.commit()
    except Exception:
        session.rollback()
        raise

    flagged = 0
    scored = 0
    statuses: dict[str, int] = {}
    dispatched = 0
    try:
        if cleared_ids:
            _refresh_contract_product_index(session, tenant_id, settings)
        if run_inline:
            for txn_id in cleared_ids:
                try:
                    result = process_transaction_maverick_spend(
                        session=session,
                        tenant_id=tenant_id,
                        transaction_id=txn_id,
                        settings=settings,
                    )
                    scored += 1
                    status = str(result.get("status") or "unknown")
                    statuses[status] = statuses.get(status, 0) + 1
                    if status == "alert_created":
                        flagged += 1
                except Exception as item_exc:
                    logger.warning(
                        "maverick_gcs_item_detect_failed",
                        tenant_id=tenant_id,
                        transaction_id=txn_id,
                        error=str(item_exc),
                    )
        else:
            for txn_id in cleared_ids:
                try:
                    detect_maverick_spend_for_transaction.delay(
                        tenant_id=tenant_id, transaction_id=txn_id
                    )
                    dispatched += 1
                except Exception as dispatch_exc:
                    logger.warning(
                        "maverick_gcs_item_dispatch_failed",
                        tenant_id=tenant_id,
                        transaction_id=txn_id,
                        error=str(dispatch_exc),
                    )
    finally:
        session.close()

    logger.info(
        "maverick_gcs_scan_completed",
        tenant_id=tenant_id,
        keys=len(keys),
        promoted=promoted,
        cleared=len(cleared_ids),
        scored=scored,
        flagged=flagged,
        dispatched=dispatched,
        failed_keys=len(failed_keys),
    )
    return {
        "tenant_id": tenant_id,
        "status": "completed",
        "keys": keys,
        "failed_keys": failed_keys,
        "promoted": promoted,
        "cleared": len(cleared_ids),
        "scored": scored,
        "flagged": flagged,
        "dispatched": dispatched,
        "outcomes": statuses,
    }


@celery_app.task(
    bind=True,
    name="zellovest.workers.tasks.maverick_spend.sync_contract_products_to_qdrant",
    queue=QUEUE_ANALYTICS,
    max_retries=5,
)
def sync_contract_products_to_qdrant(self: Any, tenant_id: str) -> dict[str, Any]:
    """Embed currently active contracted software products in Qdrant for a tenant."""
    logger.info("sync_contract_products_to_qdrant_started", tenant_id=tenant_id)
    factory = get_session_factory()
    session = factory()
    try:
        summary = sync_active_contract_products(session, tenant_id)
        logger.info(
            "sync_contract_products_to_qdrant_completed",
            tenant_id=tenant_id,
            **summary,
        )
        return {"tenant_id": tenant_id, **summary}
    except VoyageRateLimitError as exc:
        session.rollback()
        logger.warning(
            "sync_contract_products_to_qdrant_rate_limited",
            tenant_id=tenant_id,
            retry_after_seconds=exc.retry_after_seconds,
            retries=self.request.retries,
        )
        raise self.retry(exc=exc, countdown=exc.retry_after_seconds, max_retries=5)
    finally:
        session.close()
