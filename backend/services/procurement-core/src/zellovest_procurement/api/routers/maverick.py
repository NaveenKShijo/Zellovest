"""Maverick Spend Detection API Router (Procurement Core)."""

from __future__ import annotations

import uuid
from typing import Any

from celery import Celery
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from zellovest_shared.db.core import Department, Employee, Vendor
from zellovest_shared.db.intelligence import AlertStatus, MaverickAlert
from zellovest_shared.db.transact import CardTransaction, Contract, ContractTermsVersion
from zellovest_shared.logging_conf import get_logger

from zellovest_procurement.api.deps import get_db_session
from zellovest_procurement.config import get_procurement_core_settings
from zellovest_procurement.schemas.maverick import (
    ContractProductReindexRequest,
    ContractProductReindexStatusSchema,
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
            Contract,
            ContractTermsVersion,
            Vendor,
        )
        .join(CardTransaction, MaverickAlert.transaction_id == CardTransaction.id)
        .outerjoin(Employee, MaverickAlert.employee_id == Employee.id)
        .outerjoin(Department, Employee.department_id == Department.id)
        .outerjoin(Contract, MaverickAlert.overlap_contract_id == Contract.id)
        .outerjoin(
            ContractTermsVersion,
            MaverickAlert.overlap_contract_term_id == ContractTermsVersion.id,
        )
        .outerjoin(Vendor, Contract.vendor_id == Vendor.id)
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

    for alert, txn, emp, dept, contract, contract_term, ven in rows:
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
        annual_savings = round(amount_val * 12.0, 2)
        matched = evidence.get("matched_contract_product") or {}
        overlap_obj = None
        if contract is not None and contract_term is not None:
            overlap_obj = SoftwareOverlapSchema(
                unmanagedTool=unmanaged_tool,
                unmanagedCategory=unmanaged_cat,
                approvedAlternative=str(
                    matched.get("name")
                    or contract_term.description
                    or contract_term.product_code
                    or ""
                ),
                approvedContractId=str(contract.id),
                approvedVendorName=ven.name if ven else "",
                cosineSimilarity=round(overlap_score_val, 2),
                sharedCapabilities=list(matched.get("shared_capabilities") or []),
                recommendedAction=alert.recommended_action or "Procurement review recommended.",
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

    from datetime import UTC, datetime
    from decimal import Decimal
    from zellovest_shared.db.intelligence import (
        DecisionPacket,
        SavingsKind,
        SavingsLedgerEntry,
        SavingsStatus,
    )
    from zellovest_shared.decision_packets import (
        ENTITY_MAVERICK_ALERT,
        STATUS_ACTIONED,
        STATUS_DISMISSED,
        STATUS_PENDING_REVIEW,
    )
    from zellovest_shared.pricing import to_decimal

    packet = await session.scalar(
        select(DecisionPacket).where(
            DecisionPacket.tenant_id == tenant_id,
            DecisionPacket.entity_type == ENTITY_MAVERICK_ALERT,
            DecisionPacket.entity_id == alert.id,
        )
    )
    if packet is not None:
        packet.status = (
            STATUS_DISMISSED
            if alert.status == AlertStatus.DISMISSED
            else STATUS_ACTIONED
            if alert.status == AlertStatus.MIGRATED
            else STATUS_PENDING_REVIEW
        )
        packet.actioned_at = datetime.now(UTC) if alert.status != AlertStatus.OPEN else None

    if alert.status == AlertStatus.MIGRATED:
        txn = await session.get(CardTransaction, alert.transaction_id)
        if txn is not None and txn.is_recurring and to_decimal(txn.amount) > Decimal("0"):
            existing_saving = await session.scalar(
                select(SavingsLedgerEntry).where(
                    SavingsLedgerEntry.tenant_id == tenant_id,
                    SavingsLedgerEntry.source_type == "maverick_consolidation",
                    SavingsLedgerEntry.source_id == alert.id,
                )
            )
            if existing_saving is None:
                session.add(
                    SavingsLedgerEntry(
                        tenant_id=tenant_id,
                        vendor_id=txn.vendor_id,
                        source_type="maverick_consolidation",
                        source_id=alert.id,
                        amount=(to_decimal(txn.amount) * Decimal("12")).quantize(Decimal("0.01")),
                        currency=txn.currency or "USD",
                        kind=SavingsKind.AVOIDANCE,
                        status=SavingsStatus.POTENTIAL,
                        notes=f"Auto-staged upon consolidating {alert.merchant_name}.",
                    )
                )

    await session.commit()
    logger.info("maverick_alert_status_updated", alert_id=alert_id, status=payload.status)

    return {"id": alert_id, "status": alert.status.value, "updated": True}


_ANALYTICS_QUEUE = "analytics_tasks"
_BATCH_TASK = "zellovest.workers.tasks.maverick_spend.detect_maverick_spend"
_GCS_SCAN_TASK = "zellovest.workers.tasks.maverick_spend.scan_maverick_spend_from_gcs"
_CONTRACT_PRODUCT_SYNC_TASK = (
    "zellovest.workers.tasks.maverick_spend.sync_contract_products_to_qdrant"
)


def _celery_client() -> Celery:
    """Return a Redis-backed Celery client for analytics dispatch and status."""
    settings = get_procurement_core_settings()
    return Celery(
        "zellovest.procurement",
        broker=settings.redis_url,
        backend=settings.redis_url,
    )


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
    celery = _celery_client()
    task = celery.send_task(task_name, kwargs=kwargs, queue=queue)
    return str(task.id or "")


@router.post(
    "/contract-products/reindex",
    response_model=ContractProductReindexStatusSchema,
    status_code=status.HTTP_202_ACCEPTED,
)
async def reindex_contract_products(
    body: ContractProductReindexRequest,
) -> ContractProductReindexStatusSchema:
    """Queue a refresh of vectors for real, active contract product lines."""
    try:
        task_id = _dispatch_task(
            _CONTRACT_PRODUCT_SYNC_TASK,
            {"tenant_id": body.tenant_id},
        )
    except Exception as exc:
        logger.error(
            "contract_product_reindex_dispatch_failed",
            tenant_id=body.tenant_id,
            error_class=type(exc).__name__,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Approved-software indexing worker is unavailable; retry shortly.",
        ) from exc

    logger.info(
        "contract_product_reindex_queued",
        tenant_id=body.tenant_id,
        task_id=task_id,
    )
    return ContractProductReindexStatusSchema(task_id=task_id, status="PENDING")


@router.get(
    "/contract-products/reindex/{task_id}",
    response_model=ContractProductReindexStatusSchema,
)
async def get_contract_product_reindex_status(
    task_id: str,
) -> ContractProductReindexStatusSchema:
    """Return the latest Celery status and result for a product-index refresh."""
    result = _celery_client().AsyncResult(task_id)
    task_status = str(result.status)
    if task_status == "SUCCESS" and isinstance(result.result, dict):
        summary_keys = (
            "active_terms",
            "indexed_products",
            "excluded_non_saas",
            "enrichment_failures",
        )
        summary = {
            key: int(result.result[key])
            for key in summary_keys
            if key in result.result and result.result[key] is not None
        }
        return ContractProductReindexStatusSchema(
            task_id=task_id,
            status=task_status,
            summary=summary,
        )
    error = str(result.result) if task_status == "FAILURE" else None
    return ContractProductReindexStatusSchema(
        task_id=task_id,
        status=task_status,
        error=error,
    )


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
