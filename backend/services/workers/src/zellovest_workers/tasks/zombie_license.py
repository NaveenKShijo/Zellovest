"""Worker 7: Zombie License Analytics Engine (deterministic batch).

Per PRD 18: rule-based, NOT agentic. License -> last activity / frequency /
utilization -> inactive threshold (30/60/90d) -> potential zombie license.
Computes utilization rate, inactive seats, cost of inactive seats and
recoverable spend for MCP-1 / Ask AI. Agents may later investigate WHY.
"""

from typing import Any

from zellovest_shared.logging_conf import get_logger
from zellovest_workers.celery_app import QUEUE_ANALYTICS, celery_app

logger = get_logger(__name__)

DEFAULT_THRESHOLDS = (30, 60, 90)


def is_zombie(last_activity_days_ago: int | None, threshold_days: int = 60) -> bool:
    """Deterministic inactivity predicate (None = never active = zombie)."""
    if last_activity_days_ago is None:
        return True
    return last_activity_days_ago >= threshold_days


@celery_app.task(
    name="zellovest.workers.tasks.zombie_license.scan_zombie_licenses",
    queue=QUEUE_ANALYTICS,
    max_retries=3,
)
def scan_zombie_licenses(
    tenant_id: str, threshold_days: int = 60, vendor_id: str | None = None
) -> dict[str, Any]:
    """Scan license seats vs Okta activity and compute reclaimable waste."""
    logger.info(
        "zombie_scan_started",
        tenant_id=tenant_id,
        threshold_days=threshold_days,
        vendor_id=vendor_id,
    )
    # TODO: load licenses + Okta usage snapshots, apply is_zombie per seat,
    # aggregate {purchased, active, inactive, utilization_rate,
    # inactive_cost, recoverable_spend} and persist for MCP-1.
    return {
        "tenant_id": tenant_id,
        "vendor_id": vendor_id,
        "threshold_days": threshold_days,
        "status": "queued",
        "note": "Okta usage join TODO",
    }
