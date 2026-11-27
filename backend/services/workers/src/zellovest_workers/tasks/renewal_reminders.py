"""Celery tasks for monitoring contract renewal notice deadlines."""

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select

from zellovest_shared.db.core import Vendor
from zellovest_shared.db.intelligence import SeatForecast, Workflow, WorkflowStatus, WorkflowType
from zellovest_shared.db.session import get_session_factory
from zellovest_shared.db.transact import Contract, ContractStatus
from zellovest_shared.logging_conf import get_logger
from zellovest_workers.celery_app import QUEUE_ANALYTICS, celery_app

logger = get_logger(__name__)


def _nearest_forecast_horizon(days_to_renewal: int) -> int:
    """Map days-to-renewal onto the closest supported seat-forecast horizon."""
    for horizon in (30, 60, 90, 120):
        if days_to_renewal <= horizon:
            return horizon
    return 120


def scan_notice_deadlines_sync() -> dict[str, Any]:
    """Scan active contracts, schedule reminders, and trigger dossier/forecast cascades."""
    today = datetime.now(UTC).date()
    factory = get_session_factory()
    created_count = 0
    scanned_count = 0
    dossiers_queued = 0
    forecasts_queued = 0

    dossier_candidates: list[tuple[str, str]] = []
    forecast_candidates: list[tuple[str, int, str]] = []

    with factory() as session:
        # Find active contracts with renewal_date or end_date set
        stmt = (
            select(Contract, Vendor)
            .outerjoin(Vendor, Contract.vendor_id == Vendor.id)
            .where(
                Contract.status == ContractStatus.ACTIVE,
                Contract.renewal_date.is_not(None),
            )
        )
        rows = session.execute(stmt).all()
        scanned_count = len(rows)

        recent_cutoff = today - timedelta(days=14)
        for contract, vendor in rows:
            if not contract.renewal_date:
                continue

            notice_days = contract.notice_period_days if contract.notice_period_days is not None else 30
            notice_deadline = contract.renewal_date - timedelta(days=notice_days)
            days_to_notice = (notice_deadline - today).days
            days_to_renewal = (contract.renewal_date - today).days

            # Pre-compute renewal dossiers automatically at <= 90d before notice deadline
            if -14 <= days_to_notice <= 90:
                dossier_candidates.append((contract.tenant_id, str(contract.id)))

            # Trigger seat forecasting when crossing T-120/90/60/30 renewal milestones
            if 0 <= days_to_renewal <= 120 and contract.vendor_id is not None:
                horizon = _nearest_forecast_horizon(days_to_renewal)
                recent_forecast = session.scalar(
                    select(SeatForecast.id).where(
                        SeatForecast.tenant_id == contract.tenant_id,
                        SeatForecast.vendor_id == contract.vendor_id,
                        SeatForecast.horizon_days == horizon,
                        SeatForecast.forecast_date >= recent_cutoff,
                    )
                )
                if recent_forecast is None:
                    forecast_candidates.append(
                        (contract.tenant_id, horizon, str(contract.vendor_id))
                    )

            # Flag auto-renew contracts approaching notice deadline within 30 days
            if contract.auto_renew and 0 <= days_to_notice <= 30:
                existing = session.scalar(
                    select(Workflow).where(
                        Workflow.tenant_id == contract.tenant_id,
                        Workflow.workflow_type == WorkflowType.RENEWAL_NEGOTIATION,
                        Workflow.reference_type == "renewal",
                        Workflow.reference_id == contract.id,
                        Workflow.status.in_([WorkflowStatus.PENDING, WorkflowStatus.IN_PROGRESS]),
                    )
                )

                if existing is None:
                    vendor_name = vendor.name if vendor else "Vendor"
                    wf = Workflow(
                        tenant_id=contract.tenant_id,
                        workflow_type=WorkflowType.RENEWAL_NEGOTIATION,
                        title=f"Urgent Notice Deadline Reminder: {vendor_name} ({contract.contract_number})",
                        description=(
                            f"Contract {contract.contract_number} auto-renews on {contract.renewal_date.isoformat()}. "
                            f"Written opt-out notice deadline is on {notice_deadline.isoformat()} ({days_to_notice} days away). "
                            "Pre-built negotiation brief is ready for review before the deadline passes."
                        ),
                        reference_type="renewal",
                        reference_id=contract.id,
                        status=WorkflowStatus.PENDING,
                        due_at=datetime.combine(notice_deadline, datetime.min.time(), tzinfo=UTC),
                        extra={
                            "contract_id": str(contract.id),
                            "vendor_id": str(contract.vendor_id),
                            "vendor_name": vendor_name,
                            "contract_number": contract.contract_number,
                            "renewal_date": contract.renewal_date.isoformat(),
                            "notice_deadline_date": notice_deadline.isoformat(),
                            "days_to_notice": days_to_notice,
                            "automated_scan": True,
                        },
                    )
                    session.add(wf)
                    created_count += 1
                    logger.info(
                        "renewal_notice_deadline_workflow_created",
                        contract_number=contract.contract_number,
                        vendor_name=vendor_name,
                        days_to_notice=days_to_notice,
                    )

        if created_count > 0:
            session.commit()

    # Best-effort background dispatch after DB commit
    if dossier_candidates:
        try:
            from zellovest_workers.tasks.decision_packets import precompute_renewal_dossier_packet

            for t_id, c_id in dossier_candidates:
                precompute_renewal_dossier_packet.delay(tenant_id=t_id, contract_id=c_id)
                dossiers_queued += 1
        except Exception as exc:
            logger.warning("renewal_dossier_dispatch_skipped", error_class=type(exc).__name__)

    if forecast_candidates:
        try:
            from zellovest_workers.tasks.seat_forecasting import run_seat_forecast

            for t_id, horizon, v_id in forecast_candidates:
                run_seat_forecast.delay(tenant_id=t_id, horizon_days=horizon, vendor_id=v_id)
                forecasts_queued += 1
        except Exception as exc:
            logger.warning("renewal_forecast_dispatch_skipped", error_class=type(exc).__name__)

    return {
        "scanned": scanned_count,
        "reminders_created": created_count,
        "dossiers_queued": dossiers_queued,
        "forecasts_queued": forecasts_queued,
    }


@celery_app.task(
    name="zellovest.workers.tasks.renewal_reminders.scan_renewal_notice_deadlines",
    queue=QUEUE_ANALYTICS,
    max_retries=3,
)
def scan_renewal_notice_deadlines() -> dict[str, Any]:
    """Celery Beat task: scheduled scan for upcoming renewal notice deadlines."""
    try:
        return scan_notice_deadlines_sync()
    except Exception as exc:
        logger.exception("scan_renewal_notice_deadlines_failed", error=str(exc))
        raise
