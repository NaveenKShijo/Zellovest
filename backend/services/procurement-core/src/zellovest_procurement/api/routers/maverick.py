"""Maverick Spend Detection API Router (Procurement Core)."""

from __future__ import annotations

import uuid
from typing import Any

from celery import Celery
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from zellovest_shared.db.core import Department, Employee, SoftwareCatalog, Vendor
from zellovest_shared.db.intelligence import AlertStatus, MaverickAlert
from zellovest_shared.db.transact import CardTransaction
from zellovest_shared.logging_conf import get_logger

from zellovest_procurement.api.deps import get_db_session
from zellovest_procurement.config import get_procurement_core_settings
from zellovest_procurement.schemas.maverick import (
    JevDecisionScoresSchema,
    MaverickAlertItemSchema,
    MaverickSpendFeedResponse,
    MaverickSpendKPIsSchema,
    SoftwareOverlapSchema,
    TriggerDetectionRequest,
    UpdateAlertStatusRequest,
)

logger = get_logger(__name__)
router = APIRouter(prefix="/maverick-spend", tags=["maverick-spend"])


@router.get("", response_model=MaverickSpendFeedResponse)
async def get_maverick_spend_feed(
    tenant_id: str = Query(..., min_length=1),
    department: str | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    min_overlap: float = Query(default=0.0, ge=0.0, le=1.0),
    session: AsyncSession = Depends(get_db_session),
) -> MaverickSpendFeedResponse:
    """Fetch Maverick Spend alerts and aggregated KPIs for procurement dashboard."""
    stmt = (
        select(
            MaverickAlert,
            CardTransaction,
            Employee,
            Department,
            SoftwareCatalog,
            Vendor,
        )
        .join(CardTransaction, MaverickAlert.transaction_id == CardTransaction.id)
        .outerjoin(Employee, MaverickAlert.employee_id == Employee.id)
        .outerjoin(Department, Employee.department_id == Department.id)
        .outerjoin(SoftwareCatalog, MaverickAlert.overlap_catalog_id == SoftwareCatalog.id)
        .outerjoin(Vendor, SoftwareCatalog.vendor_id == Vendor.id)
        .where(MaverickAlert.tenant_id == tenant_id)
        .order_by(MaverickAlert.created_at.desc())
    )

    if status_filter and status_filter != "all":
        try:
            status_enum = AlertStatus(status_filter)
            stmt = stmt.where(MaverickAlert.status == status_enum)
        except ValueError:
            pass

    if min_overlap > 0:
        stmt = stmt.where(MaverickAlert.overlap_score >= min_overlap)

    rows = (await session.execute(stmt)).all()

    alert_items: list[MaverickAlertItemSchema] = []
    total_unmanaged_spend = 0.0
    active_alerts_count = 0
    potential_annual_savings = 0.0
    overlap_similarities: list[float] = []

    for alert, txn, emp, dept, cat, ven in rows:
        if dept is not None:
            dept_name = dept.name
        elif emp is not None and emp.department_raw:
            dept_name = emp.department_raw
        else:
            dept_name = "Unassigned"
        if department and department != "all" and dept_name != department:
            continue

        emp_first = (emp.first_name if emp else "") or ""
        emp_last = (emp.last_name if emp else "") or ""
        emp_name = f"{emp_first} {emp_last}".strip() or (
            txn.cardholder_name_raw or "Unknown Employee"
        )
        emp_email = (emp.email if emp else "") or "unknown@company.com"

        amount_val = float(txn.amount or 0.0)
        overlap_score_val = float(alert.overlap_score or 0.0)

        # Parse evidence details
        evidence = alert.decision_evidence if isinstance(alert.decision_evidence, dict) else {}
        raw_features = evidence.get("features")
        features = raw_features if isinstance(raw_features, dict) else {}
        cadence_days = int(features.get("cadence_days", 30))
        cadence_desc = (
            f"~{cadence_days}d recurring" if cadence_days <= 45 else "Annual subscription"
        )

        # Overlap data
        unmanaged_tool = features.get("product_name") or alert.merchant_name
        product_prof = evidence.get("product_profile", {})
        if not isinstance(product_prof, dict):
            product_prof = {}
        unmanaged_cat = product_prof.get("category") or "Software"
        shared_caps = list(product_prof.get("capabilities") or [])[:4]

        approved_alt = cat.name if cat else "Enterprise Software Pool"
        approved_vendor = ven.name if ven else (cat.name if cat else "Approved Vendor")

        annual_savings = round(amount_val * 12.0, 2)

        overlap_obj = SoftwareOverlapSchema(
            unmanagedTool=unmanaged_tool,
            unmanagedCategory=unmanaged_cat,
            approvedAlternative=approved_alt,
            approvedContractId=str(cat.id) if cat else "none",
            approvedVendorName=approved_vendor,
            cosineSimilarity=round(overlap_score_val, 2),
            sharedCapabilities=shared_caps,
            recommendedAction=alert.recommended_action
            or "Review and migrate to approved enterprise alternative.",
            employeeEmail=emp_email,
            employeeName=emp_name,
            annualizedSavingsOpportunity=annual_savings,
        )

        item = MaverickAlertItemSchema(
            id=str(alert.id),
            transactionId=str(txn.id),
            merchantName=alert.merchant_name,
            amount=round(amount_val, 2),
            currency=txn.currency or "USD",
            cadenceDays=cadence_days,
            cadenceDescription=cadence_desc,
            cardLast4=txn.card_last4 or "",
            employeeId=str(emp.id) if emp else "",
            employeeName=emp_name,
            employeeEmail=emp_email,
            department=str(dept_name),
            transactionDate=txn.txn_date.isoformat()
            if txn.txn_date
            else alert.created_at.isoformat(),
            jevScores=JevDecisionScoresSchema(
                isSaasScore=float(alert.jev_is_saas_score or 0.0),
                warrantsReviewScore=float(alert.jev_review_score or 0.0),
            ),
            status=alert.status.value,
            overlap=overlap_obj,
        )
        alert_items.append(item)

        # KPI aggregations
        total_unmanaged_spend += amount_val
        if alert.status in (AlertStatus.OPEN, AlertStatus.NOTIFIED):
            active_alerts_count += 1
            potential_annual_savings += annual_savings
        if overlap_score_val > 0:
            overlap_similarities.append(overlap_score_val)

    avg_overlap = (
        round(sum(overlap_similarities) / len(overlap_similarities), 2)
        if overlap_similarities
        else 0.0
    )

    kpis = MaverickSpendKPIsSchema(
        totalUnmanagedSpend=round(total_unmanaged_spend, 2),
        activeAlertsCount=active_alerts_count,
        potentialAnnualSavings=round(potential_annual_savings, 2),
        avgOverlapSimilarity=avg_overlap,
    )

    return MaverickSpendFeedResponse(alerts=alert_items, kpis=kpis)


@router.patch("/{alert_id}/status")
async def update_maverick_alert_status(
    alert_id: str,
    payload: UpdateAlertStatusRequest,
    tenant_id: str = Query(..., min_length=1),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """Update maverick spend alert status (e.g. notified, migrated, dismissed)."""
    try:
        alert_uuid = uuid.UUID(alert_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid alert UUID format")

    stmt = select(MaverickAlert).where(
        MaverickAlert.id == alert_uuid,
        MaverickAlert.tenant_id == tenant_id,
    )
    alert = (await session.execute(stmt)).scalars().first()
    if not alert:
        raise HTTPException(status_code=404, detail="Maverick alert not found")

    alert.status = AlertStatus(payload.status)
    await session.commit()
    logger.info("maverick_alert_status_updated", alert_id=alert_id, status=payload.status)

    return {"id": alert_id, "status": alert.status.value, "updated": True}


_ANALYTICS_QUEUE = "analytics_tasks"
_BATCH_TASK = "zellovest.workers.tasks.maverick_spend.detect_maverick_spend"
_GCS_SCAN_TASK = "zellovest.workers.tasks.maverick_spend.scan_maverick_spend_from_gcs"


def _dispatch_task(
    task_name: str,
    kwargs: dict[str, Any],
    queue: str = _ANALYTICS_QUEUE,
) -> str:
    """Publish one analytics task to the worker broker and return its id.

    Args:
        task_name: Registered Celery task name.
        kwargs: JSON-serializable task keyword arguments.
        queue: Target queue (analytics by default).

    Returns:
        The Celery task id (``None`` is never returned; a missing id is
        normalised to an empty string).

    Raises:
        Exception: Propagated so the API can return a clear 5xx when the
            broker is unreachable.
    """
    settings = get_procurement_core_settings()
    celery = Celery("zellovest.procurement", broker=settings.redis_url)
    task = celery.send_task(task_name, kwargs=kwargs, queue=queue)
    return str(task.id or "")


@router.post("/trigger", status_code=status.HTTP_202_ACCEPTED)
async def trigger_maverick_detection(
    body: TriggerDetectionRequest,
) -> dict[str, Any]:
    """Trigger maverick spend detection over DB rows or a GCS bronze object.

    A call without ``gcs_key``/``sync_id`` scans transactions already in
    ``card_transactions``. Supplying either one scans that bronze-lake object
    (or sync partition) end to end: normalize -> Jev/catalog identification ->
    persist alerts.
    """
    scan_gcs = body.source != "db"
    if scan_gcs:
        task_name = _GCS_SCAN_TASK
        kwargs: dict[str, Any] = {
            "tenant_id": body.tenant_id,
            "gcs_key": (body.gcs_key or "").strip() or None,
            "sync_id": (body.sync_id or "").strip() or None,
            "prefix": (body.prefix or "").strip() or None,
            "lookback_days": body.lookback_days,
            "run_inline": body.run_inline,
        }
        mode = "gcs_scan"
    else:
        task_name = _BATCH_TASK
        kwargs = {
            "tenant_id": body.tenant_id,
            "lookback_days": body.lookback_days,
        }
        mode = "db_batch"

    try:
        task_id = _dispatch_task(task_name, kwargs)
    except Exception as exc:
        logger.error(
            "maverick_trigger_dispatch_failed",
            tenant_id=body.tenant_id,
            task_name=task_name,
            error_class=type(exc).__name__,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Maverick worker queue is unavailable; retry shortly.",
        ) from exc

    logger.info(
        "maverick_detection_triggered_via_api",
        tenant_id=body.tenant_id,
        task_id=task_id,
        mode=mode,
        gcs_key=kwargs.get("gcs_key"),
        sync_id=kwargs.get("sync_id"),
    )
    return {
        "status": "queued",
        "task_id": task_id,
        "tenant_id": body.tenant_id,
        "lookback_days": body.lookback_days,
        "mode": mode,
        "gcs_key": kwargs.get("gcs_key"),
        "sync_id": kwargs.get("sync_id"),
    }
