"""Celery application entry point (broker + backend = Redis).

Control plane enqueues lightweight ticket metadata only
(``tenant_id``, ``cursor``, ``event_id``, ``sync_id``) — raw API payloads
never touch Redis.
"""

from celery import Celery
from kombu import Queue

from zellovest_shared.logging_conf import configure_logging, get_logger

configure_logging()
logger = get_logger(__name__)

QUEUE_INGESTION = "ingestion_tasks"
QUEUE_DOCUMENTS = "document_tasks"
QUEUE_ANALYTICS = "analytics_tasks"


def make_celery(broker_url: str = "redis://localhost:6379/0") -> Celery:
    """Build the Celery app with JSON serialization and bounded retries."""
    app = Celery("zellovest.workers", broker=broker_url, backend=broker_url)
    app.conf.update(
        task_serializer="json",
        result_serializer="json",
        accept_content=["json"],
        timezone="UTC",
        enable_utc=True,
        task_acks_late=True,
        worker_prefetch_multiplier=1,
        task_reject_on_worker_lost=True,
        task_queues=(
            Queue(QUEUE_INGESTION, routing_key=QUEUE_INGESTION),
            Queue(QUEUE_DOCUMENTS, routing_key=QUEUE_DOCUMENTS),
            Queue(QUEUE_ANALYTICS, routing_key=QUEUE_ANALYTICS),
        ),
        task_routes={
            "zellovest.workers.tasks.ingestion.*": {"queue": QUEUE_INGESTION},
            "zellovest.workers.tasks.document_ocr.*": {"queue": QUEUE_DOCUMENTS},
            "zellovest.workers.tasks.ap_audit.*": {"queue": QUEUE_ANALYTICS},
            "zellovest.workers.tasks.maverick_spend.*": {"queue": QUEUE_ANALYTICS},
            "zellovest.workers.tasks.zombie_license.*": {"queue": QUEUE_ANALYTICS},
        },
        task_default_queue=QUEUE_INGESTION,
    )
    return app


celery_app = make_celery()

# Import tasks so workers register them (must stay at bottom).
import zellovest_workers.tasks  # noqa: F401, E402
