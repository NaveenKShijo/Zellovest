"""Unified in-app Decision Feed router (Procurement Core)."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from zellovest_shared.db.intelligence import (
    AlertStatus,
    DecisionPacket,
    ExceptionStatus,
    MaverickAlert,
    ReconciliationException,
    SavingsKind,
    SavingsLedgerEntry,
    SavingsStatus,
    SeatForecast,
    Workflow,
    WorkflowStatus,
    WorkflowType,
)
from zellovest_shared.db.models import (
    ExtractionArtifact,
    IngestionSyncCheckpoint,
    SyncStatus,
    Upload,
    UploadStatus,
    User,
)
from zellovest_shared.db.transact import CardTransaction, Invoice
from zellovest_shared.decision_packets import (
    ENTITY_CONTRACT,
    ENTITY_EXCEPTION,
    ENTITY_MAVERICK_ALERT,
    STATUS_ACTIONED,
    STATUS_DISMISSED,
    STATUS_PENDING_REVIEW,
    build_ap_investigation_packet_sync,
    build_maverick_review_packet_sync,
    build_renewal_dossier_packet_sync,
    refresh_tenant_decision_packets_sync,
)
from zellovest_shared.logging_conf import get_logger
from zellovest_shared.pricing import to_decimal

from zellovest_procurement.api.deps import get_db_session, get_optional_user
from zellovest_procurement.schemas.decision_feed import (
    DecisionFeedRefreshResponse,
    DecisionFeedResponse,
    DecisionFeedSummary,
    DecisionPacketActionRequest,
    DecisionPacketActionResponse,
    DecisionPacketItem,
)

logger = get_logger(__name__)
router = APIRouter(prefix="/decision-feed", tags=["decision-feed"])

_VALID_ACTIONS = frozenset(
    {"acknowledge", "resolve", "dismiss", "mark_migrated", "create_workflow"}
)


def _serialize_packet(row: DecisionPacket) -> DecisionPacketItem:
    """Convert a DecisionPacket ORM row into the API schema."""
    return DecisionPacketItem(
        id=row.id,
        tenant_id=row.tenant_id,
        packet_type=row.packet_type,
        entity_type=row.entity_type,
        entity_id=row.entity_id,
        vendor_id=row.vendor_id,
        title=row.title,
        summary=row.summary,
        recommended_action=row.recommended_action,
        financial_impact=float(row.financial_impact) if row.financial_impact is not None else None,
        currency=row.currency,
        urgency_date=row.urgency_date,
        source_hash=row.source_hash,
        payload=row.payload or {},
        status=row.status,
        actioned_at=row.actioned_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


async def _stage_potential_savings_if_needed(
    session: AsyncSession,
    *,
    tenant_id: str,
    source_type: str,
    source_id: UUID,
    vendor_id: UUID | None,
    amount: Decimal,
    currency: str,
    kind: SavingsKind,
    notes: str | None,
) -> UUID | None:
    """Idempotently record a POTENTIAL SavingsLedgerEntry for a positive deterministic saving."""
    if amount <= Decimal("0"):
        return None
    existing = await session.scalar(
        select(SavingsLedgerEntry).where(
            SavingsLedgerEntry.tenant_id == tenant_id,
            SavingsLedgerEntry.source_type == source_type,
            SavingsLedgerEntry.source_id == source_id,
        )
    )
    if existing is not None:
        return existing.id

    entry = SavingsLedgerEntry(
        tenant_id=tenant_id,
        vendor_id=vendor_id,
        source_type=source_type,
        source_id=source_id,
        amount=amount.quantize(Decimal("0.01")),
        currency=(currency or "USD")[:3],
        kind=kind,
        status=SavingsStatus.POTENTIAL,
        notes=notes,
    )
    session.add(entry)
    await session.flush()
    return entry.id


@router.get("", response_model=DecisionFeedResponse)
async def get_decision_feed(
    packet_type: str | None = Query(default=None),
    status_filter: str = Query(default="pending_review", alias="status"),
    limit: int = Query(default=25, ge=1, le=100),
    auto_hydrate: bool = Query(default=True),
    tenant_id: str | None = Query(default=None),
    user: User | None = Depends(get_optional_user),
    session: AsyncSession = Depends(get_db_session),
) -> DecisionFeedResponse:
    """Return prioritized pre-computed decision packets and live queue context."""
    active_tenant = (user.tenant_id if user else None) or tenant_id or "default-org"

    existing_count = (
        await session.scalar(
            select(func.count(DecisionPacket.id)).where(
                DecisionPacket.tenant_id == active_tenant,
            )
        )
    ) or 0

    if auto_hydrate and existing_count == 0:
        try:
            await session.run_sync(
                lambda sync_sess: refresh_tenant_decision_packets_sync(sync_sess, active_tenant)
            )
        except Exception as exc:
            logger.warning(
                "decision_feed_auto_hydrate_skipped",
                tenant_id=active_tenant,
                error_class=type(exc).__name__,
            )

    query = select(DecisionPacket).where(DecisionPacket.tenant_id == active_tenant)
    if packet_type and packet_type != "all":
        query = query.where(DecisionPacket.packet_type == packet_type)
    if status_filter and status_filter != "all":
        query = query.where(DecisionPacket.status == status_filter)

    urgency_null_last = case((DecisionPacket.urgency_date.is_(None), 1), else_=0)
    rows = (
        await session.execute(
            query.order_by(
                urgency_null_last.asc(),
                DecisionPacket.urgency_date.asc(),
                func.coalesce(DecisionPacket.financial_impact, 0).desc(),
                DecisionPacket.created_at.desc(),
            ).limit(limit)
        )
    ).scalars().all()

    pending_rows = (
        await session.execute(
            select(
                DecisionPacket.packet_type,
                func.count(DecisionPacket.id),
                func.coalesce(func.sum(DecisionPacket.financial_impact), 0),
            )
            .where(
                DecisionPacket.tenant_id == active_tenant,
                DecisionPacket.status == STATUS_PENDING_REVIEW,
            )
            .group_by(DecisionPacket.packet_type)
        )
    ).all()

    type_counts = {"ap_investigation": 0, "renewal_dossier": 0, "maverick_review": 0}
    total_impact = Decimal("0.00")
    pending_count = 0
    for p_type, cnt, amt in pending_rows:
        count_int = int(cnt or 0)
        pending_count += count_int
        if p_type in type_counts:
            type_counts[p_type] = count_int
        total_impact += to_decimal(amt)

    docs_review_needed = int(
        (
            await session.scalar(
                select(func.count(Upload.id))
                .outerjoin(ExtractionArtifact, ExtractionArtifact.upload_id == Upload.id)
                .where(
                    Upload.tenant_id == active_tenant,
                    Upload.status == UploadStatus.COMPLETED,
                    or_(
                        ExtractionArtifact.review_status == "pending",
                        and_(
                            or_(
                                ExtractionArtifact.review_status.is_(None),
                                ExtractionArtifact.review_status != "committed",
                            ),
                            func.coalesce(ExtractionArtifact.extraction_confidence, 1.0) < 0.80,
                        ),
                    ),
                )
            )
        )
        or 0
    )

    invoice_extras = (
        await session.execute(
            select(Invoice.extra).where(Invoice.tenant_id == active_tenant)
        )
    ).scalars().all()
    total_invoices = len(invoice_extras)
    audited_invoices = sum(
        1
        for extra in invoice_extras
        if isinstance(extra, dict) and extra.get("commercial_reconciled_at")
    )
    unreconciled_invoices_count = max(0, total_invoices - audited_invoices)

    active_workflows_count = int(
        (
            await session.scalar(
                select(func.count(Workflow.id)).where(
                    Workflow.tenant_id == active_tenant,
                    Workflow.status.in_([WorkflowStatus.PENDING, WorkflowStatus.IN_PROGRESS]),
                )
            )
        )
        or 0
    )

    potential_savings_total = float(
        (
            await session.scalar(
                select(func.coalesce(func.sum(SavingsLedgerEntry.amount), 0)).where(
                    SavingsLedgerEntry.tenant_id == active_tenant,
                )
            )
        )
        or 0
    )

    last_sync_at = await session.scalar(
        select(func.max(IngestionSyncCheckpoint.finished_at)).where(
            IngestionSyncCheckpoint.tenant_id == active_tenant,
            IngestionSyncCheckpoint.status == SyncStatus.SUCCESS,
        )
    )

    return DecisionFeedResponse(
        items=[_serialize_packet(row) for row in rows],
        summary=DecisionFeedSummary(
            pending_count=pending_count,
            total_financial_impact=float(total_impact),
            ap_count=type_counts["ap_investigation"],
            renewal_count=type_counts["renewal_dossier"],
            maverick_count=type_counts["maverick_review"],
            documents_review_needed=docs_review_needed,
            unreconciled_invoices_count=unreconciled_invoices_count,
            active_workflows_count=active_workflows_count,
            potential_savings_total=potential_savings_total,
            last_sync_at=last_sync_at,
        ),
    )


@router.get("/by-entity", response_model=DecisionPacketItem)
async def get_packet_by_entity(
    entity_type: str = Query(..., min_length=1),
    entity_id: UUID = Query(...),
    tenant_id: str | None = Query(default=None),
    user: User | None = Depends(get_optional_user),
    session: AsyncSession = Depends(get_db_session),
) -> DecisionPacketItem:
    """Return a pre-computed packet for one entity, building on demand if missing."""
    active_tenant = (user.tenant_id if user else None) or tenant_id or "default-org"

    packet = await session.scalar(
        select(DecisionPacket).where(
            DecisionPacket.tenant_id == active_tenant,
            DecisionPacket.entity_type == entity_type,
            DecisionPacket.entity_id == entity_id,
        )
    )
    if packet is not None:
        return _serialize_packet(packet)

    def _build_sync(sync_sess: Any) -> DecisionPacket | None:
        built: DecisionPacket | None = None
        if entity_type == ENTITY_EXCEPTION:
            built = build_ap_investigation_packet_sync(sync_sess, active_tenant, entity_id)
        elif entity_type == ENTITY_CONTRACT:
            built = build_renewal_dossier_packet_sync(sync_sess, active_tenant, entity_id)
        elif entity_type == ENTITY_MAVERICK_ALERT:
            built = build_maverick_review_packet_sync(sync_sess, active_tenant, entity_id)
        if built is not None:
            sync_sess.commit()
        return built

    built_packet = await session.run_sync(_build_sync)
    if built_packet is None:
        raise HTTPException(status_code=404, detail="Decision packet could not be built for entity")

    refreshed = await session.scalar(
        select(DecisionPacket).where(
            DecisionPacket.tenant_id == active_tenant,
            DecisionPacket.entity_type == entity_type,
            DecisionPacket.entity_id == entity_id,
        )
    )
    if refreshed is None:
        raise HTTPException(status_code=404, detail="Decision packet not found")
    return _serialize_packet(refreshed)


@router.post("/refresh", response_model=DecisionFeedRefreshResponse)
async def refresh_decision_feed(
    tenant_id: str | None = Query(default=None),
    user: User | None = Depends(get_optional_user),
    session: AsyncSession = Depends(get_db_session),
) -> DecisionFeedRefreshResponse:
    """Synchronously refresh pre-computed decision packets for the active tenant."""
    active_tenant = (user.tenant_id if user else None) or tenant_id or "default-org"
    counts = await session.run_sync(
        lambda sync_sess: refresh_tenant_decision_packets_sync(sync_sess, active_tenant)
    )
    return DecisionFeedRefreshResponse(
        tenant_id=active_tenant,
        ap_investigation=counts.get("ap_investigation", 0),
        renewal_dossier=counts.get("renewal_dossier", 0),
        maverick_review=counts.get("maverick_review", 0),
    )


@router.post("/{packet_id}/action", response_model=DecisionPacketActionResponse)
async def execute_decision_packet_action(
    packet_id: UUID,
    body: DecisionPacketActionRequest,
    tenant_id: str | None = Query(default=None),
    user: User | None = Depends(get_optional_user),
    session: AsyncSession = Depends(get_db_session),
) -> DecisionPacketActionResponse:
    """Execute one in-app decision action (no external Slack/email notifications)."""
    if body.action not in _VALID_ACTIONS:
        expected = sorted(_VALID_ACTIONS)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unsupported action '{body.action}'. Expected one of: {expected}.",
        )

    active_tenant = (user.tenant_id if user else None) or tenant_id or "default-org"
    packet = (
        await session.execute(
            select(DecisionPacket)
            .where(
                DecisionPacket.id == packet_id,
                DecisionPacket.tenant_id == active_tenant,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if packet is None:
        raise HTTPException(status_code=404, detail="Decision packet not found")

    now = datetime.now(UTC)
    workflow_id: UUID | None = None
    savings_entry_id: UUID | None = None
    message = "Decision recorded."

    if packet.entity_type == ENTITY_EXCEPTION:
        exc = await session.scalar(
            select(ReconciliationException).where(
                ReconciliationException.id == packet.entity_id,
                ReconciliationException.tenant_id == active_tenant,
            )
        )
        if body.action in {"acknowledge", "resolve", "dismiss"} and exc is not None:
            new_status = (
                ExceptionStatus.ACKNOWLEDGED
                if body.action == "acknowledge"
                else ExceptionStatus.RESOLVED
                if body.action == "resolve"
                else ExceptionStatus.DISMISSED
            )
            exc.status = new_status
            exc.resolved_at = now if body.action in {"resolve", "dismiss"} else None
            if body.action in {"resolve", "dismiss"}:
                remaining_open = (
                    await session.scalar(
                        select(func.count(ReconciliationException.id)).where(
                            ReconciliationException.invoice_id == exc.invoice_id,
                            ReconciliationException.tenant_id == active_tenant,
                            ReconciliationException.id != exc.id,
                            ReconciliationException.status.in_(
                                [ExceptionStatus.OPEN, ExceptionStatus.ACKNOWLEDGED]
                            ),
                        )
                    )
                    or 0
                )
                if remaining_open == 0:
                    inv = await session.get(Invoice, exc.invoice_id)
                    if inv is not None:
                        inv.status = "approved"
            if body.action == "resolve" and exc.variance_amount:
                inv = await session.get(Invoice, exc.invoice_id)
                savings_entry_id = await _stage_potential_savings_if_needed(
                    session,
                    tenant_id=active_tenant,
                    source_type="overbill",
                    source_id=exc.id,
                    vendor_id=inv.vendor_id if inv else packet.vendor_id,
                    amount=abs(to_decimal(exc.variance_amount)),
                    currency=inv.currency if inv else packet.currency,
                    kind=SavingsKind.HARD_CASH,
                    notes=body.notes or f"Resolved AP exception on {packet.title}",
                )
            message = f"Exception marked {new_status.value}."

    elif packet.entity_type == ENTITY_MAVERICK_ALERT:
        alert = await session.scalar(
            select(MaverickAlert).where(
                MaverickAlert.id == packet.entity_id,
                MaverickAlert.tenant_id == active_tenant,
            )
        )
        if body.action == "mark_migrated" and alert is not None:
            alert.status = AlertStatus.MIGRATED
            txn = await session.get(CardTransaction, alert.transaction_id)
            if txn is not None and txn.is_recurring:
                savings_entry_id = await _stage_potential_savings_if_needed(
                    session,
                    tenant_id=active_tenant,
                    source_type="maverick_consolidation",
                    source_id=alert.id,
                    vendor_id=txn.vendor_id,
                    amount=to_decimal(txn.amount) * Decimal("12"),
                    currency=txn.currency,
                    kind=SavingsKind.AVOIDANCE,
                    notes=body.notes or f"Consolidated {alert.merchant_name} to approved tool",
                )
            message = "Marked consolidated to approved software."
        elif body.action == "dismiss" and alert is not None:
            alert.status = AlertStatus.DISMISSED
            message = "Maverick alert dismissed as approved exception."

    elif packet.entity_type == ENTITY_CONTRACT:
        if body.action == "resolve" and packet.vendor_id is not None:
            latest_forecast = await session.scalar(
                select(SeatForecast)
                .where(
                    SeatForecast.tenant_id == active_tenant,
                    SeatForecast.vendor_id == packet.vendor_id,
                )
                .order_by(SeatForecast.forecast_date.desc(), SeatForecast.created_at.desc())
                .limit(1)
            )
            if (
                latest_forecast is not None
                and latest_forecast.recommended_seats < latest_forecast.current_seats
            ):
                savings_entry_id = await _stage_potential_savings_if_needed(
                    session,
                    tenant_id=active_tenant,
                    source_type="seat_reduction_pre_renewal",
                    source_id=latest_forecast.id,
                    vendor_id=latest_forecast.vendor_id,
                    amount=to_decimal(
                        latest_forecast.savings_estimate or latest_forecast.shelfware_amount
                    ),
                    currency="USD",
                    kind=SavingsKind.AVOIDANCE,
                    notes=body.notes or f"Pre-renewal seat optimization for {packet.title}",
                )
            message = "Renewal decision recorded."

    if body.action == "create_workflow":
        wf_type = (
            WorkflowType.RENEWAL_NEGOTIATION
            if packet.entity_type == ENTITY_CONTRACT
            else WorkflowType.INVOICE_APPROVAL
            if packet.entity_type == ENTITY_EXCEPTION
            else WorkflowType.HUMAN_REVIEW
        )
        wf = Workflow(
            tenant_id=active_tenant,
            workflow_type=wf_type,
            title=packet.title,
            description=body.notes or packet.recommended_action or packet.summary,
            reference_type=packet.entity_type,
            reference_id=packet.entity_id,
            assignee_user_id=user.id if user else None,
            status=WorkflowStatus.PENDING,
            due_at=(
                datetime.combine(packet.urgency_date, datetime.min.time(), tzinfo=UTC)
                if packet.urgency_date
                else None
            ),
            extra={"packet_id": str(packet.id), "packet_type": packet.packet_type},
        )
        session.add(wf)
        await session.flush()
        workflow_id = wf.id
        message = "In-app procurement workflow task created."

    packet.status = STATUS_DISMISSED if body.action == "dismiss" else STATUS_ACTIONED
    packet.actioned_by_user_id = user.id if user else None
    packet.actioned_at = now
    payload = dict(packet.payload or {})
    if workflow_id is not None:
        payload["workflow_id"] = str(workflow_id)
    if savings_entry_id is not None:
        payload["savings_entry_id"] = str(savings_entry_id)
    if body.notes:
        payload["action_notes"] = body.notes
    packet.payload = payload

    await session.commit()
    await session.refresh(packet)
    logger.info(
        "decision_packet_action_executed",
        tenant_id=active_tenant,
        packet_id=str(packet.id),
        action=body.action,
        workflow_id=str(workflow_id) if workflow_id else None,
        savings_entry_id=str(savings_entry_id) if savings_entry_id else None,
    )
    return DecisionPacketActionResponse(
        packet=_serialize_packet(packet),
        workflow_id=workflow_id,
        savings_entry_id=savings_entry_id,
        message=message,
    )
