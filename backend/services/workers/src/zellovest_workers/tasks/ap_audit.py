"""Worker 5: AP Audit & Compliance Reconciliation Engine (deterministic).

Per PRD 9-12: NEVER use an LLM for price math. Flow:
1. New invoice -> identify vendor/product -> applicable contract version
   (effective_from/effective_to, amendment lineage).
2. Apply deterministic rules: price, quantity, date, discount, tax,
   payment-term, freight, contract-specific conditions.
3. Emit variance + exception rows; the Investigation Agent (Ask AI) explains
   them later using MCP-1 tools.
"""

from decimal import Decimal
from typing import Any

from zellovest_shared.logging_conf import get_logger
from zellovest_workers.celery_app import QUEUE_ANALYTICS, celery_app

logger = get_logger(__name__)


def compare_line_item(contract_price: Decimal, invoice_price: Decimal) -> dict[str, Any]:
    """Deterministic price comparison for one line item."""
    if contract_price == 0:
        return {"variance_pct": None, "exception": True, "reason": "zero_contract_price"}
    variance = (invoice_price - contract_price) / contract_price * Decimal("100")
    return {
        "contract_price": str(contract_price),
        "invoice_price": str(invoice_price),
        "variance_pct": float(variance),
        "exception": abs(variance) > Decimal("0.01"),
    }


@celery_app.task(
    name="zellovest.workers.tasks.ap_audit.reconcile_invoice",
    queue=QUEUE_ANALYTICS,
    max_retries=3,
)
def reconcile_invoice(tenant_id: str, invoice_id: str) -> dict[str, Any]:
    """Reconcile one invoice against its applicable contract version."""
    logger.info("reconcile_started", tenant_id=tenant_id, invoice_id=invoice_id)
    # TODO: load invoice + vendor + applicable contract version from
    # procurement-core DB, run rule set, write discrepancies + audit log.
    return {
        "tenant_id": tenant_id,
        "invoice_id": invoice_id,
        "status": "queued",
        "note": "deterministic 3-way match TODO",
    }


@celery_app.task(name="zellovest.workers.tasks.ap_audit.reconcile_vendor", queue=QUEUE_ANALYTICS)
def reconcile_vendor(tenant_id: str, vendor_id: str) -> dict[str, Any]:
    """Backfill reconciliation for all open invoices of a vendor."""
    logger.info("reconcile_vendor_started", tenant_id=tenant_id, vendor_id=vendor_id)
    return {"tenant_id": tenant_id, "vendor_id": vendor_id, "status": "queued"}
