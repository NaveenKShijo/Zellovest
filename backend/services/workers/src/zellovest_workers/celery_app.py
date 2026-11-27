"""Celery application entry point (broker + backend = Redis).

Control plane enqueues lightweight ticket metadata only
(``tenant_id``, ``cursor``, ``event_id``, ``sync_id``) — raw API payloads
never touch Redis.
"""

import os

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
            "zellovest.workers.tasks.document_ocr.stage_document": {"queue": QUEUE_INGESTION},
            "zellovest.workers.tasks.document_ocr.*": {"queue": QUEUE_DOCUMENTS},
            "zellovest.workers.tasks.document_classify.*": {"queue": QUEUE_DOCUMENTS},
            "zellovest.workers.tasks.ap_audit.*": {"queue": QUEUE_ANALYTICS},
            "zellovest.workers.tasks.maverick_spend.*": {"queue": QUEUE_ANALYTICS},
            "zellovest.workers.tasks.zombie_license.*": {"queue": QUEUE_ANALYTICS},
            "zellovest.workers.tasks.forecasting.*": {"queue": QUEUE_ANALYTICS},
            "zellovest.workers.tasks.mlops.*": {"queue": QUEUE_ANALYTICS},
            "zellovest.workers.tasks.renewal_reminders.*": {"queue": QUEUE_ANALYTICS},
            "zellovest.workers.tasks.decision_packets.*": {"queue": QUEUE_ANALYTICS},
            "zellovest.workers.tasks.maintenance.*": {"queue": QUEUE_INGESTION},
        },
        task_default_queue=QUEUE_INGESTION,
        beat_schedule={
            "mark-expired-uploads": {
                "task": "zellovest.workers.tasks.maintenance.mark_expired_uploads",
                "schedule": 60.0,
                "options": {"queue": QUEUE_INGESTION},
            },
            "purge-expired-uploads": {
                "task": "zellovest.workers.tasks.maintenance.purge_expired_uploads",
                "schedule": 900.0,
                "options": {"queue": QUEUE_INGESTION},
            },
            "scheduled-integrations-sync": {
                "task": "zellovest.workers.tasks.ingestion.scheduled_integrations_sync",
                "schedule": 3600.0,
                "options": {"queue": QUEUE_INGESTION},
            },
            "renew-expiring-drive-watches": {
                "task": "zellovest.workers.tasks.ingestion.renew_expiring_drive_watches",
                "schedule": 43200.0,
                "options": {"queue": QUEUE_INGESTION},
            },
            "scan-renewal-notice-deadlines": {
                "task": "zellovest.workers.tasks.renewal_reminders.scan_renewal_notice_deadlines",
                "schedule": 86400.0,  # daily scan
                "options": {"queue": QUEUE_ANALYTICS},
            },
            "refresh-decision-packets-hourly": {
                "task": "zellovest.workers.tasks.decision_packets.refresh_all_tenant_decision_packets",
                "schedule": 3600.0,
                "options": {"queue": QUEUE_ANALYTICS},
            },
            "dispatch-seat-forecasts-biweekly": {
                "task": "zellovest.workers.tasks.forecasting.dispatch_seat_forecasts",
                "schedule": 1296000.0,  # every 15 days
                "options": {"queue": QUEUE_ANALYTICS},
            },
            "run-ml-drift-monitoring-weekly": {
                "task": "zellovest.workers.tasks.mlops.run_drift_monitoring",
                "schedule": 604800.0,  # weekly MLOps drift & evaluation check
                "options": {"queue": QUEUE_ANALYTICS},
            },
        },
    )
    return app


celery_app = make_celery(os.getenv("REDIS_URL", "redis://localhost:6379/0"))

# Import tasks so workers register them (must stay at bottom).
import zellovest_workers.tasks  # noqa: F401, E402
