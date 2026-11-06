"""Celery task registration.

Importing this package registers all worker tasks with the Celery app.
"""

from zellovest_workers.tasks import (
    ap_audit,
    document_classify,
    document_index,
    document_ocr,
    document_promote,
    document_structured_extract,
    document_verify,
    ingestion,
    maintenance,
    maverick_spend,
    zombie_license,
)

__all__ = [
    "ap_audit",
    "document_classify",
    "document_index",
    "document_ocr",
    "document_promote",
    "document_structured_extract",
    "document_verify",
    "ingestion",
    "maintenance",
    "maverick_spend",
    "zombie_license",
]
