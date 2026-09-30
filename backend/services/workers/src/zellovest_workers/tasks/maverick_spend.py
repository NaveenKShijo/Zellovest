"""Worker 6: Maverick Spend ML Detection (unsupervised).

Per PRD 14-17, Stage 1 is ML/analytical (NOT agentic):
features = cadence, recurrence interval, amount, merchant category/domain,
frequency, history, employee patterns. DBSCAN / IsolationForest flags likely
recurring SaaS; Stages 2-3 resolve merchant context and vector-match against
the approved catalog (Ask AI / MCP-1 serve the results).
"""

from typing import Any

from zellovest_shared.logging_conf import get_logger
from zellovest_workers.celery_app import QUEUE_ANALYTICS, celery_app

logger = get_logger(__name__)


def build_transaction_features(transactions: list[dict[str, Any]]) -> Any:
    """Build numeric feature matrix for clustering (lazy sklearn import)."""
    import numpy as np

    # Minimal placeholder features: [amount, cadence_days, frequency].
    # TODO: merchant-category encoding, recurrence-interval FFT, employee aggregates.
    rows = [
        [
            float(t.get("amount", 0) or 0),
            float(t.get("cadence_days", 30) or 30),
            float(t.get("frequency_90d", 1) or 1),
        ]
        for t in transactions
    ]
    return np.array(rows, dtype=float)


@celery_app.task(
    name="zellovest.workers.tasks.maverick_spend.detect_maverick_spend",
    queue=QUEUE_ANALYTICS,
    max_retries=3,
)
def detect_maverick_spend(
    tenant_id: str, lookback_days: int = 90, min_amount: float = 5.0
) -> dict[str, Any]:
    """Run unsupervised clustering over recent card transactions."""
    from sklearn.ensemble import IsolationForest

    logger.info("maverick_detect_started", tenant_id=tenant_id, lookback_days=lookback_days)
    # TODO: load transactions from procurement-core DB / bronze lake.
    transactions: list[dict[str, Any]] = []
    if not transactions:
        return {"tenant_id": tenant_id, "flagged": 0, "status": "no_data"}

    X = build_transaction_features(transactions)
    model = IsolationForest(contamination=0.05, random_state=42)
    scores = model.fit_predict(X)
    flagged = int((scores == -1).sum())
    logger.info("maverick_detect_complete", tenant_id=tenant_id, flagged=flagged)
    # TODO: merchant resolution + catalog vector overlap (Stage 2-3),
    # persist alerts for MCP-1 get_maverick_spend().
    return {"tenant_id": tenant_id, "flagged": flagged, "scored": len(transactions)}
