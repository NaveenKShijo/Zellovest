"""Background workers package.

Workers (per PRD 27.5.3):
- Worker 4: Document OCR & Extraction (Celery / GPU pods)
- Worker 5: AP Audit & Compliance Reconciliation Engine (deterministic)
- Worker 6: Maverick Spend ML Detection (scikit-learn)
- Worker 7: Zombie License Analytics Engine (deterministic batch)
- Ingestion tasks: Ramp polling + webhook handlers, Okta sync
"""

__version__ = "0.1.0"
