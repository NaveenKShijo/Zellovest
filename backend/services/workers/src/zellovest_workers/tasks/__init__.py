"""Celery task registration.

Importing this package registers all worker tasks with the Celery app.
"""

from zellovest_workers.tasks import ap_audit, document_ocr, ingestion, maverick_spend, zombie_license

__all__ = ["ap_audit", "document_ocr", "ingestion", "maverick_spend", "zombie_license"]
