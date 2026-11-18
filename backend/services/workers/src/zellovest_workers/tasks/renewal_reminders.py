"""Celery tasks for monitoring contract renewal notice deadlines."""

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import and_, select

from zellovest_shared.db.core import Vendor
from zellovest_shared.db.intelligence import Workflow, WorkflowStatus, WorkflowType
from zellovest_shared.db.session import get_session_factory
from zellovest_shared.db.transact import Contract, ContractStatus
from zellovest_shared.logging_conf import get_logger
from zellovest_workers.celery_app import QUEUE_ANALYTICS, celery_app

logger = get_logger(__name__)


def scan_notice_deadlines_sync() -> dict[str, Any]:
    """Scan active contracts and schedule reminder workflows before notice deadlines."""
    today = datetime.now(UTC).date()
    factory = get_session_factory()
    created_count = 0
    scanned_count = 0

    with factory() as session:
        # Find active contracts with auto_renew = True and renewal_date set
        stmt = (
            select(Contract, Vendor)
            .outerjoin(Vendor, Contract.vendor_id == Vendor.id)
            .where(
                Contract.status == ContractStatus.ACTIVE,
                Contract.auto_renew.is_(True),
                Contract.renewal_date.is_not(None),
            )
        )
        rows = session.execute(stmt).all()
        scanned_count = len(rows)

        for contract, vendor in rows:
            if not contract.renewal_date:
                continue

            notice_days = contract.notice_period_days if contract.notice_period_days is not None else 30
            notice_deadline = contract.renewal_date - timedelta(days=notice_days)
            days_to_notice = (notice_deadline - today).days

            # Flag contracts approaching notice deadline within 30 days
            if 0 <= days_to_notice <= 30:
                # Check for existing reminder workflow
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
                            "Prepare negotiation brief and engage vendor before the deadline passes."
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

    return {"scanned": scanned_count, "reminders_created": created_count}


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
