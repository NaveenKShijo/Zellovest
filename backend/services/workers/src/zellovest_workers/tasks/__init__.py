"""Celery task registration.

Importing this package registers all worker tasks with the Celery app.
"""

from zellovest_workers.tasks import (
    ap_audit,
    decision_packets,
    document_classify,
    document_index,
    document_ocr,
    document_promote,
    document_structured_extract,
    document_verify,
    ingestion,
    maintenance,
    maverick_spend,
    ml_ops,
    renewal_reminders,
    seat_forecasting,
    zombie_license,
)

__all__ = [
    "ap_audit",
    "decision_packets",
    "document_classify",
    "document_index",
    "document_ocr",
    "document_promote",
    "document_structured_extract",
    "document_verify",
    "ingestion",
    "maintenance",
    "maverick_spend",
    "ml_ops",
    "renewal_reminders",
    "seat_forecasting",
    "zombie_license",
]
