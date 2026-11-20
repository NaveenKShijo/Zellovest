"""Savings-ledger handlers owned by Procurement Core.

The handlers translate already-detected, deterministic source records into
auditable *potential* savings. They never mark a value as verified; that
separate finance-review transition must be performed by an authorized user.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from zellovest_shared.db.intelligence import (
    AlertStatus,
    MaverickAlert,
    ReconciliationException,
    SavingsKind,
    SavingsLedgerEntry,
    SavingsStatus,
    SeatForecast,
)
from zellovest_shared.db.models import User
from zellovest_shared.db.transact import CardTransaction, Invoice
from zellovest_shared.logging_conf import get_logger
from zellovest_shared.pricing import to_decimal

from zellovest_procurement.api.deps import get_current_user, get_db_session
from zellovest_procurement.schemas.savings import (
    MaverickConsolidationSavingsRequest,
    OverbillSavingsRequest,
    SavingsLedgerListResponse,
    SavingsLedgerResponse,
    SeatReductionSavingsRequest,
)

logger = get_logger(__name__)
router = APIRouter(prefix="/savings-ledger", tags=["savings-ledger"])

_FINANCE_VERIFIER_ROLES = frozenset({"admin", "finance", "finance_approver"})


def _serialize(entry: SavingsLedgerEntry, *, reused: bool = False) -> SavingsLedgerResponse:
    """Convert a persistence model into the public ledger response."""
    return SavingsLedgerResponse(
        id=entry.id,
        tenant_id=entry.tenant_id,
        vendor_id=entry.vendor_id,
        source_type=entry.source_type,
        source_id=entry.source_id,
        amount=to_decimal(entry.amount),
        currency=entry.currency,
        kind=entry.kind.value,
        status=entry.status.value,
        verified_by_user_id=entry.verified_by_user_id,
        verified_at=entry.verified_at,
        notes=entry.notes,
        created_at=entry.created_at,
        reused=reused,
    )


async def _existing_entry(
    session: AsyncSession, tenant_id: str, source_type: str, source_id: UUID
) -> SavingsLedgerEntry | None:
    """Find the idempotent ledger entry for one source event."""
    return await session.scalar(
        select(SavingsLedgerEntry).where(
            SavingsLedgerEntry.tenant_id == tenant_id,
            SavingsLedgerEntry.source_type == source_type,
            SavingsLedgerEntry.source_id == source_id,
        )
    )


async def _create_potential_entry(
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
) -> SavingsLedgerResponse:
    """Create one potential entry, returning an existing entry on replay."""
    existing = await _existing_entry(session, tenant_id, source_type, source_id)
    if existing is not None:
        return _serialize(existing, reused=True)
    if amount <= Decimal("0"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="savings source does not contain a positive deterministic amount",
        )

    entry = SavingsLedgerEntry(
        tenant_id=tenant_id,
        vendor_id=vendor_id,
        source_type=source_type,
        source_id=source_id,
        amount=amount.quantize(Decimal("0.01")),
        currency=currency,
        kind=kind,
        status=SavingsStatus.POTENTIAL,
        notes=notes,
    )
    session.add(entry)
    try:
        await session.commit()
        await session.refresh(entry)
    except IntegrityError as exc:
        await session.rollback()
        existing = await _existing_entry(session, tenant_id, source_type, source_id)
        if existing is not None:
            return _serialize(existing, reused=True)
        logger.exception(
            "savings_ledger_idempotency_lookup_failed",
            tenant_id=tenant_id,
            source_type=source_type,
            source_id=str(source_id),
            error_class=type(exc).__name__,
        )
        raise HTTPException(status_code=409, detail="conflicting savings ledger source") from exc
    except Exception as exc:
        await session.rollback()
        logger.exception(
            "savings_ledger_create_failed",
            tenant_id=tenant_id,
            source_type=source_type,
            source_id=str(source_id),
            error_class=type(exc).__name__,
        )
        raise HTTPException(
            status_code=500, detail="unable to create savings ledger entry"
        ) from exc

    logger.info(
        "savings_ledger_entry_created",
        tenant_id=tenant_id,
        ledger_entry_id=str(entry.id),
        source_type=source_type,
        amount=str(entry.amount),
        kind=kind.value,
    )
    return _serialize(entry)


@router.post("/overbill", response_model=SavingsLedgerResponse, status_code=status.HTTP_201_CREATED)
async def register_overbill_savings(
    body: OverbillSavingsRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> SavingsLedgerResponse:
    """Register an open positive AP variance as potential hard-cash recovery."""
    exception = await session.scalar(
        select(ReconciliationException).where(
            ReconciliationException.id == body.exception_id,
            ReconciliationException.tenant_id == current_user.tenant_id,
        )
    )
    if exception is None:
        raise HTTPException(status_code=404, detail="reconciliation exception not found")
    invoice = await session.scalar(
        select(Invoice).where(
            Invoice.id == exception.invoice_id,
            Invoice.tenant_id == current_user.tenant_id,
        )
    )
    if invoice is None:
        raise HTTPException(status_code=409, detail="exception source invoice is unavailable")
    return await _create_potential_entry(
        session,
        tenant_id=current_user.tenant_id,
        source_type="overbill",
        source_id=exception.id,
        vendor_id=invoice.vendor_id,
        amount=to_decimal(exception.variance_amount),
        currency=invoice.currency,
        kind=SavingsKind.HARD_CASH,
        notes=body.notes,
    )


@router.post(
    "/seat-reduction", response_model=SavingsLedgerResponse, status_code=status.HTTP_201_CREATED
)
async def register_seat_reduction_savings(
    body: SeatReductionSavingsRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> SavingsLedgerResponse:
    """Register an optimizer-backed pre-renewal reduction as cost avoidance."""
    forecast = await session.scalar(
        select(SeatForecast).where(
            SeatForecast.id == body.forecast_id,
            SeatForecast.tenant_id == current_user.tenant_id,
        )
    )
    if forecast is None:
        raise HTTPException(status_code=404, detail="seat forecast not found")
    if forecast.recommended_seats >= forecast.current_seats:
        raise HTTPException(
            status_code=422,
            detail="forecast does not recommend a seat reduction",
        )
    amount = to_decimal(forecast.savings_estimate or forecast.shelfware_amount)
    return await _create_potential_entry(
        session,
        tenant_id=current_user.tenant_id,
        source_type="seat_reduction_pre_renewal",
        source_id=forecast.id,
        vendor_id=forecast.vendor_id,
        amount=amount,
        currency="USD",
        kind=SavingsKind.AVOIDANCE,
        notes=body.notes,
    )


@router.post(
    "/maverick-consolidation",
    response_model=SavingsLedgerResponse,
    status_code=status.HTTP_201_CREATED,
)
async def register_maverick_consolidation_savings(
    body: MaverickConsolidationSavingsRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> SavingsLedgerResponse:
    """Register a migrated recurring SaaS alert as potential cost avoidance."""
    alert = await session.scalar(
        select(MaverickAlert).where(
            MaverickAlert.id == body.alert_id,
            MaverickAlert.tenant_id == current_user.tenant_id,
        )
    )
    if alert is None:
        raise HTTPException(status_code=404, detail="maverick alert not found")
    if alert.status != AlertStatus.MIGRATED:
        raise HTTPException(
            status_code=409,
            detail="maverick alert must be marked migrated before recording savings",
        )
    transaction = await session.scalar(
        select(CardTransaction).where(
            CardTransaction.id == alert.transaction_id,
            CardTransaction.tenant_id == current_user.tenant_id,
        )
    )
    if transaction is None:
        raise HTTPException(status_code=409, detail="maverick source transaction is unavailable")
    if not transaction.is_recurring:
        raise HTTPException(
            status_code=422,
            detail="maverick source transaction is not marked recurring",
        )
    return await _create_potential_entry(
        session,
        tenant_id=current_user.tenant_id,
        source_type="maverick_consolidation",
        source_id=alert.id,
        vendor_id=transaction.vendor_id,
        amount=to_decimal(transaction.amount) * Decimal("12"),
        currency=transaction.currency,
        kind=SavingsKind.AVOIDANCE,
        notes=body.notes,
    )


@router.post("/{entry_id}/verify", response_model=SavingsLedgerResponse)
async def verify_savings_entry(
    entry_id: UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> SavingsLedgerResponse:
    """Record finance verification for a potential ledger entry."""
    if current_user.role not in _FINANCE_VERIFIER_ROLES:
        raise HTTPException(status_code=403, detail="finance verification role required")
    entry = await session.scalar(
        select(SavingsLedgerEntry).where(
            SavingsLedgerEntry.id == entry_id,
            SavingsLedgerEntry.tenant_id == current_user.tenant_id,
        )
    )
    if entry is None:
        raise HTTPException(status_code=404, detail="savings ledger entry not found")
    if entry.status == SavingsStatus.VERIFIED:
        return _serialize(entry, reused=True)
    entry.status = SavingsStatus.VERIFIED
    entry.verified_by_user_id = current_user.id
    entry.verified_at = datetime.now(UTC)
    try:
        await session.commit()
        await session.refresh(entry)
    except Exception as exc:
        await session.rollback()
        logger.exception(
            "savings_ledger_verify_failed",
            tenant_id=current_user.tenant_id,
            ledger_entry_id=str(entry_id),
            error_class=type(exc).__name__,
        )
        raise HTTPException(
            status_code=500, detail="unable to verify savings ledger entry"
        ) from exc
    logger.info(
        "savings_ledger_entry_verified",
        tenant_id=current_user.tenant_id,
        ledger_entry_id=str(entry.id),
        verifier_id=str(current_user.id),
    )
    return _serialize(entry)


@router.get("", response_model=SavingsLedgerListResponse)
async def list_savings_ledger(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
    vendor_id: UUID | None = Query(default=None),
) -> SavingsLedgerListResponse:
    """List auditable savings entries and split deterministic ledger totals."""
    query = select(SavingsLedgerEntry).where(SavingsLedgerEntry.tenant_id == current_user.tenant_id)
    if vendor_id is not None:
        query = query.where(SavingsLedgerEntry.vendor_id == vendor_id)
    entries = (await session.scalars(query.order_by(SavingsLedgerEntry.created_at.desc()))).all()
    totals = {
        "verified_hard_cash": Decimal("0"),
        "verified_avoidance": Decimal("0"),
        "potential_hard_cash": Decimal("0"),
        "potential_avoidance": Decimal("0"),
    }
    for entry in entries:
        prefix = "verified" if entry.status == SavingsStatus.VERIFIED else "potential"
        suffix = "hard_cash" if entry.kind == SavingsKind.HARD_CASH else "avoidance"
        totals[f"{prefix}_{suffix}"] += to_decimal(entry.amount)
    return SavingsLedgerListResponse(
        items=[_serialize(entry) for entry in entries],
        **totals,
    )
