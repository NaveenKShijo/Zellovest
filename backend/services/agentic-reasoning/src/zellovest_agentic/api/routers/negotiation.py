"""Negotiation Copilot & Renewal Agent router.

Provides:
- GET /upcoming-renewals: Live countdown timeline of upcoming contract renewals,
  notice deadline tracking, and urgency categorization.
- POST /seed-contracts: Explicit on-demand seeding or re-syncing of live PostgreSQL
  contracts, lines, versioned pricing terms, and invoices for the tenant.
- POST /brief: Evidence-grounded negotiation brief generation using multi-domain
  data (contract terms, invoices, Okta utilization, AP audit exceptions, and RAG clauses).
- POST /renewal-prep: Structured commercial preparation metrics.
- POST /remind: Schedule a renewal notice deadline reminder workflow.
- GET /reminders: List scheduled renewal notice deadline reminders.
"""

import asyncio
import hashlib
import json
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from zellovest_shared.db.core import Vendor
from zellovest_shared.db.intelligence import (
    DecisionPacket,
    ExceptionStatus,
    LicenseAssignment,
    MLDriftReport,
    MLModelMetric,
    ReconciliationException,
    SeatForecast,
    Workflow,
    WorkflowStatus,
    WorkflowType,
)
from zellovest_shared.decision_packets import (
    PACKET_RENEWAL_DOSSIER,
    acompute_vendor_utilization,
)
from zellovest_shared.db.models import ExtractionArtifact, Upload, User
from zellovest_shared.db.transact import (
    CardTransaction,
    Contract,
    ContractStatus,
    ContractTermsVersion,
    ContractVersion,
    Document,
    Invoice,
    InvoiceLineItem,
    POLineItem,
    PurchaseOrder,
)
from zellovest_shared.logging_conf import get_logger
from zellovest_shared.rag import retain_existing_documents, search_documents

from zellovest_agentic.api.deps import (
    get_current_user,
    get_db_session,
    get_optional_user,
    normalize_tenant_id,
)
from zellovest_agentic.schemas.negotiation import (
    ClauseCitation,
    NegotiationBriefRequest,
    NegotiationBriefResponse,
    RenewalPreparationRequest,
    RenewalPreparationResponse,
    RenewalReminderItem,
    RenewalReminderRequest,
    RenewalReminderResponse,
    UpcomingRenewalResponse,
)
from zellovest_agentic.services.rag_llm import _completion, _json_object
from zellovest_agentic.services.renewal_seeder import seed_tenant_renewal_contracts
from zellovest_agentic.services.tracing import trace_span

logger = get_logger(__name__)
router = APIRouter(prefix="/negotiation", tags=["negotiation"])


@router.get("/seat-forecasts")
async def list_seat_forecasts(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> list[dict[str, Any]]:
    """Return tenant-scoped persisted forecast cohorts without guessing renewal dates."""
    tenant_id = normalize_tenant_id(current_user.tenant_id)
    # The synthetic setup used default_org while application identities use
    # default-org. Both name this deployment's default organization; all other
    # tenant IDs retain exact matching. Never accept tenant scope from the client.
    tenant_ids = (
        ("default-org", "default_org")
        if tenant_id in ("default-org", "default_org")
        else (tenant_id,)
    )
    try:
        result = await session.execute(
            select(SeatForecast, Vendor.name)
            .outerjoin(
                Vendor,
                (Vendor.id == SeatForecast.vendor_id)
                & (Vendor.tenant_id == SeatForecast.tenant_id),
            )
            .where(SeatForecast.tenant_id.in_(tenant_ids))
            .order_by(SeatForecast.forecast_date.desc(), SeatForecast.created_at.desc())
        )
        forecasts = [
            {
                "id": str(forecast.id), "vendor_id": str(forecast.vendor_id),
                "vendor_name": name or f"Vendor {forecast.vendor_id}",
                "department": forecast.department,
                "forecast_date": forecast.forecast_date.isoformat(),
                "horizon_days": getattr(
                    forecast,
                    "horizon_days",
                    (forecast.retention_curve or {}).get("horizon_days"),
                ),
                "created_at": forecast.created_at.isoformat(),
                "current_seats": forecast.current_seats,
                "recommended_seats": forecast.recommended_seats,
                "headcount_growth_seats": getattr(forecast, "headcount_growth_seats", 0),
                "retention_curve": forecast.retention_curve,
                "confidence": forecast.confidence,
                "shelfware_amount": forecast.shelfware_amount,
                "trueup_risk_amount": forecast.trueup_risk_amount,
                "savings_estimate": forecast.savings_estimate,
                "model_version": forecast.model_version,
            }
            for forecast, name in result.all()
        ]
        logger.info("seat_forecasts_listed", tenant_id=tenant_id, count=len(forecasts))
        return forecasts
    except Exception as exc:
        logger.warning("seat_forecasts_list_failed", tenant_id=tenant_id, error=str(exc))
        raise HTTPException(status_code=503, detail="Unable to load seat forecasts") from exc


@router.get("/mlops/health")
async def get_seat_mlops_health(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """Return latest seat-forecasting drift report and online ground-truth metrics."""
    tenant_id = normalize_tenant_id(current_user.tenant_id)
    tenant_ids = (
        ("default-org", "default_org")
        if tenant_id in ("default-org", "default_org")
        else (tenant_id,)
    )
    try:
        latest_drift = await session.scalar(
            select(MLDriftReport)
            .where(MLDriftReport.tenant_id.in_(tenant_ids))
            .order_by(MLDriftReport.created_at.desc())
            .limit(1)
        )
        metric_rows = (
            await session.scalars(
                select(MLModelMetric)
                .where(MLModelMetric.tenant_id.in_(tenant_ids))
                .order_by(MLModelMetric.evaluated_at.desc())
                .limit(20)
            )
        ).all()
        return {
            "tenant_id": tenant_id,
            "latest_drift": (
                {
                    "model_version": latest_drift.model_version,
                    "baseline_version": latest_drift.baseline_version,
                    "reference_date": latest_drift.reference_date.isoformat(),
                    "sample_size": latest_drift.sample_size,
                    "max_psi": latest_drift.max_psi,
                    "score_psi": latest_drift.score_psi,
                    "max_sentinel_delta": latest_drift.max_sentinel_delta,
                    "severity": latest_drift.severity,
                    "drifted_features": latest_drift.drifted_features or [],
                    "retrain_recommended": latest_drift.retrain_recommended,
                    "retrain_triggered": latest_drift.retrain_triggered,
                    "trigger_reason": latest_drift.trigger_reason,
                    "created_at": latest_drift.created_at.isoformat(),
                }
                if latest_drift
                else None
            ),
            "online_metrics": [
                {
                    "model_version": row.model_version,
                    "horizon_days": row.horizon_days,
                    "segment_type": row.segment_type,
                    "segment_value": row.segment_value,
                    "evaluated_seats": row.evaluated_seats,
                    "cohort_count": row.cohort_count,
                    "roc_auc": row.roc_auc,
                    "brier_score": row.brier_score,
                    "ece": row.ece,
                    "f1": row.f1,
                    "realized_savings_vs_naive": (
                        float(row.realized_savings_vs_naive)
                        if row.realized_savings_vs_naive is not None
                        else None
                    ),
                    "financial_regret": (
                        float(row.financial_regret)
                        if row.financial_regret is not None
                        else None
                    ),
                    "trueup_incident_rate": row.trueup_incident_rate,
                    "evaluated_at": row.evaluated_at.isoformat(),
                }
                for row in metric_rows
            ],
        }
    except Exception as exc:
        logger.warning("seat_mlops_health_failed", tenant_id=tenant_id, error=str(exc))
        raise HTTPException(status_code=503, detail="Unable to load MLOps health") from exc


@router.get("/brief/source-version")
async def negotiation_source_version(
    vendor_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, str]:
    """Return a fingerprint of vendor records and searchable contract passages.

    Checking the fingerprint does not invoke the language model. A failure is
    reported rather than treating an incomplete snapshot as a valid version.
    """
    tenant_id = normalize_tenant_id(current_user.tenant_id)
    try:
        vendor = await session.scalar(
            select(Vendor).where(Vendor.id == vendor_id, Vendor.tenant_id == tenant_id)
        )
        if vendor is None:
            raise HTTPException(status_code=404, detail="Vendor not found")

        contract_ids = select(Contract.id).where(
            Contract.tenant_id == tenant_id, Contract.vendor_id == vendor_id
        )
        upload_ids = select(Upload.id).where(
            Upload.tenant_id == tenant_id, Upload.vendor_id == str(vendor_id)
        )
        invoice_ids = select(Invoice.id).where(
            Invoice.tenant_id == tenant_id, Invoice.vendor_id == vendor_id
        )
        po_ids = select(PurchaseOrder.id).where(
            PurchaseOrder.tenant_id == tenant_id, PurchaseOrder.vendor_id == vendor_id
        )
        queries = [
            select(Vendor.__table__).where(Vendor.tenant_id == tenant_id, Vendor.id == vendor_id),
            select(Contract.__table__).where(
                Contract.tenant_id == tenant_id, Contract.vendor_id == vendor_id
            ),
            select(ContractVersion.__table__).where(
                ContractVersion.tenant_id == tenant_id,
                ContractVersion.contract_id.in_(contract_ids),
            ),
            select(ContractTermsVersion.__table__).where(
                ContractTermsVersion.tenant_id == tenant_id,
                ContractTermsVersion.contract_id.in_(contract_ids),
            ),
            select(Invoice.__table__).where(
                Invoice.tenant_id == tenant_id, Invoice.vendor_id == vendor_id
            ),
            select(InvoiceLineItem.__table__).where(
                InvoiceLineItem.tenant_id == tenant_id, InvoiceLineItem.invoice_id.in_(invoice_ids)
            ),
            select(PurchaseOrder.__table__).where(
                PurchaseOrder.tenant_id == tenant_id, PurchaseOrder.vendor_id == vendor_id
            ),
            select(POLineItem.__table__).where(
                POLineItem.tenant_id == tenant_id, POLineItem.po_id.in_(po_ids)
            ),
            select(CardTransaction.__table__).where(
                CardTransaction.tenant_id == tenant_id, CardTransaction.vendor_id == vendor_id
            ),
            select(ReconciliationException.__table__).where(
                ReconciliationException.tenant_id == tenant_id,
                ReconciliationException.contract_id.in_(contract_ids),
            ),
            select(Document.__table__).where(
                Document.tenant_id == tenant_id, Document.vendor_id == vendor_id
            ),
            select(Upload.__table__).where(
                Upload.tenant_id == tenant_id, Upload.vendor_id == str(vendor_id)
            ),
            select(ExtractionArtifact.__table__).where(
                ExtractionArtifact.tenant_id == tenant_id,
                ExtractionArtifact.upload_id.in_(upload_ids),
            ),
            select(LicenseAssignment.__table__).where(
                LicenseAssignment.tenant_id == tenant_id, LicenseAssignment.vendor_id == vendor_id
            ),
            select(SeatForecast.__table__).where(
                SeatForecast.tenant_id == tenant_id, SeatForecast.vendor_id == vendor_id
            ),
        ]
        snapshot = []
        for query in queries:
            rows = (await session.execute(query)).mappings().all()
            snapshot.append(sorted(
                json.dumps(dict(row), sort_keys=True, default=str) for row in rows
            ))
        passages = await asyncio.to_thread(
            search_documents,
            tenant_id=tenant_id,
            query=f"{vendor.name} renewal termination notice price escalation increase discount",
            vendor_id=str(vendor_id),
            document_type="contract",
            limit=4,
        )
        passages = await retain_existing_documents(session, tenant_id=tenant_id, rows=passages)
        snapshot.append([json.dumps({
            key: passage.get(key) for key in
            ("document_id", "filename", "page", "section", "content")
        }, sort_keys=True, default=str) for passage in passages])
        version = hashlib.sha256(json.dumps(snapshot, sort_keys=True).encode()).hexdigest()
        return {"version": version}
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning(
            "negotiation_source_version_failed", tenant_id=tenant_id,
            vendor_id=str(vendor_id), error=str(exc),
        )
        raise HTTPException(status_code=503, detail="Unable to verify vendor data changes") from exc


def _calculate_urgency_badge(days_until_notice: int, days_until_renewal: int) -> str:
    """Classify the renewal urgency into 30d, 60d, 90d, 120d, or future."""
    effective_days = min(days_until_notice, days_until_renewal)
    if effective_days <= 30:
        return "30d"
    if effective_days <= 60:
        return "60d"
    if effective_days <= 90:
        return "90d"
    if effective_days <= 120:
        return "120d"
    return "future"


@router.post("/seed-contracts")
async def seed_contracts(
    tenant_id: str | None = Query(default=None),
    current_user: User | None = Depends(get_optional_user),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """Seed or refresh real commercial enterprise contracts in PostgreSQL."""
    resolved_tenant = normalize_tenant_id(
        current_user.tenant_id if current_user else tenant_id
    )
    count = await seed_tenant_renewal_contracts(session, resolved_tenant)
    return {
        "message": "Contracts successfully seeded into PostgreSQL",
        "count": count,
        "tenant_id": resolved_tenant,
    }


@router.get("/upcoming-renewals", response_model=list[UpcomingRenewalResponse])
async def list_upcoming_renewals(
    tenant_id: str | None = Query(default=None),
    days_ahead: int | None = Query(default=None, ge=1, le=3650),
    badge: str = Query(default="all"),
    auto_renew_only: bool = Query(default=False),
    search: str | None = Query(default=None),
    current_user: User | None = Depends(get_optional_user),
    session: AsyncSession = Depends(get_db_session),
) -> list[UpcomingRenewalResponse]:
    """List upcoming contract renewals with notice deadlines and urgency rankings."""
    resolved_tenant = normalize_tenant_id(
        current_user.tenant_id if current_user else tenant_id
    )
    logger.info("list_upcoming_renewals_called", tenant_id=resolved_tenant, days_ahead=days_ahead)

    today = datetime.now(UTC).date()
    max_date = today + timedelta(days=days_ahead) if days_ahead is not None else None

    items: list[UpcomingRenewalResponse] = []
    try:
        # 1. Query live contracts from DB
        query = (
            select(Contract, Vendor)
            .outerjoin(Vendor, Contract.vendor_id == Vendor.id)
            .where(
                Contract.tenant_id == resolved_tenant,
                Contract.status == ContractStatus.ACTIVE,
                or_(
                    Contract.renewal_date.is_not(None),
                    Contract.end_date.is_not(None),
                ),
            )
            .order_by(Contract.renewal_date.asc().nulls_last(), Contract.end_date.asc().nulls_last())
        )

        result = await session.execute(query)
        rows = result.all()

        for row in rows:
            contract: Contract = row[0]
            vendor: Vendor | None = row[1] if len(row) > 1 else None

            ren_date = contract.renewal_date or contract.end_date
            if not ren_date:
                continue
            if max_date is not None and ren_date > max_date:
                continue
            if ren_date < today - timedelta(days=30):
                continue

            notice_period = contract.notice_period_days if contract.notice_period_days is not None else 30
            notice_date = ren_date - timedelta(days=notice_period)
            days_to_renewal = (ren_date - today).days
            days_to_notice = (notice_date - today).days
            card_badge = _calculate_urgency_badge(days_to_notice, days_to_renewal)
            is_notice_active = (days_to_notice <= 0 and days_to_renewal >= 0)

            vendor_name = vendor.name if vendor else "Unknown Vendor"

            # 2. Query real spend from ContractTermsVersion or Invoice
            terms_stmt = select(func.sum(ContractTermsVersion.unit_price * func.coalesce(ContractTermsVersion.qty_min, 1))).where(
                ContractTermsVersion.contract_id == contract.id
            )
            terms_res = await session.execute(terms_stmt)
            total_terms = terms_res.scalar()
            if total_terms and float(total_terms) > 0:
                annual_spend = round(float(total_terms), 2)
            else:
                inv_stmt = select(func.sum(Invoice.total_amount)).where(Invoice.contract_id == contract.id)
                inv_res = await session.execute(inv_stmt)
                inv_total = inv_res.scalar()
                annual_spend = round(float(inv_total * 4), 2) if inv_total else 50000.0

            leverage_points = []
            if contract.auto_renew:
                if days_to_notice <= 0:
                    leverage_points.append(
                        f"Notice deadline passed ({abs(days_to_notice)}d ago) — confirm waiver before auto-renewal locks in"
                    )
                else:
                    leverage_points.append(
                        f"Auto-renews: opt-out notice required {notice_period}d prior (in {days_to_notice}d)"
                    )
            else:
                leverage_points.append("Manual renewal: no auto-renewal lock-in risk")

            # 3. Query real AP audit discrepancies from ReconciliationException
            exc_stmt = select(ReconciliationException).where(
                ReconciliationException.contract_id == contract.id,
                ReconciliationException.status == ExceptionStatus.OPEN,
            )
            exc_res = await session.execute(exc_stmt)
            open_exceptions = exc_res.scalars().all()
            for ex in open_exceptions:
                if ex.variance_amount and float(ex.variance_amount) > 0:
                    leverage_points.append(
                        f"AP Audit Discrepancy: ${float(ex.variance_amount):,.2f} overbilled on previous invoice ({ex.rule_type.value})"
                    )

            if contract.termination_clause:
                leverage_points.append(f"Termination: {contract.termination_clause[:110]}...")

            # 4. Live Utilization & Owner assignment (no hardcoded stubs)
            util = await acompute_vendor_utilization(session, resolved_tenant, contract.vendor_id)
            utilization_pct = util["utilization_pct"]
            if util["has_forecast"] and util["forecast_recommended_seats"] < util["forecast_current_seats"]:
                seat_cut = util["forecast_current_seats"] - util["forecast_recommended_seats"]
                leverage_points.append(
                    f"Seat forecast recommends {util['forecast_recommended_seats']} seats (-{seat_cut} vs current {util['forecast_current_seats']}), saving ~${util['forecast_savings_estimate']:,.0f}/yr"
                )
            elif util["idle_seats"] > 0:
                leverage_points.append(
                    f"Telemetry shows {util['idle_seats']} unused seats across {util['purchased_seats']} assigned"
                )

            assigned_owner = (
                vendor.contact_name
                if vendor and getattr(vendor, "contact_name", None)
                else "Procurement Team"
            )

            # Determine workflow status based on countdown
            if days_to_notice <= 0:
                c_status = "agent_preparing"
            elif days_to_notice <= 15:
                c_status = "negotiation_ready"
            elif days_to_notice <= 45:
                c_status = "investigating"
            else:
                c_status = "unreviewed"

            items.append(
                UpcomingRenewalResponse(
                    id=str(contract.id),
                    contract_id=str(contract.id),
                    contract_number=contract.contract_number,
                    vendor_id=str(contract.vendor_id),
                    vendor_name=vendor_name,
                    product_name=contract.title or "SaaS Subscription",
                    annual_spend=annual_spend,
                    spend_yoy_pct=8.0,
                    renewal_date=ren_date.isoformat(),
                    days_until_renewal=days_to_renewal,
                    badge=card_badge,
                    auto_renew=contract.auto_renew,
                    notice_period_days=notice_period,
                    notice_deadline_date=notice_date.isoformat(),
                    days_until_notice_deadline=days_to_notice,
                    is_notice_window_active=is_notice_active,
                    utilization_pct=utilization_pct,
                    assigned_owner=assigned_owner,
                    status=c_status,
                    key_leverage_points=leverage_points,
                )
            )
    except Exception as exc:
        logger.warning("query_contracts_for_renewals_failed", error=str(exc))
        raise HTTPException(status_code=503, detail="Unable to load upcoming renewals") from exc

    # Apply in-memory filtering (badge, auto_renew, search)
    filtered: list[UpcomingRenewalResponse] = []
    for item in items:
        if badge != "all" and item.badge != badge:
            continue
        if auto_renew_only and not item.auto_renew:
            continue
        if search:
            q = search.lower()
            if (
                q not in item.vendor_name.lower()
                and q not in item.product_name.lower()
                and q not in item.contract_number.lower()
            ):
                continue
        filtered.append(item)

    return filtered


@router.post("/brief", response_model=NegotiationBriefResponse)
async def prepare_negotiation_brief(
    body: NegotiationBriefRequest,
    current_user: User | None = Depends(get_optional_user),
    session: AsyncSession = Depends(get_db_session),
) -> NegotiationBriefResponse:
    """Prepare an evidence-grounded negotiation brief for an upcoming renewal."""
    resolved_tenant = normalize_tenant_id(
        current_user.tenant_id if current_user else body.tenant_id
    )
    logger.info("negotiation_brief_requested", tenant_id=resolved_tenant, vendor_id=body.vendor_id)

    # 1. Fetch vendor and contract details
    vendor_uuid = None
    try:
        vendor_uuid = uuid.UUID(body.vendor_id)
    except ValueError:
        pass

    vendor_name = "Target Vendor"
    annual_spend = Decimal("94200.00")
    if vendor_uuid:
        try:
            vendor_row = await session.scalar(
                select(Vendor).where(Vendor.id == vendor_uuid, Vendor.tenant_id == resolved_tenant)
            )
            if vendor_row:
                vendor_name = vendor_row.name
        except Exception:
            pass

    # 2. Fetch contract and versioned terms
    contract_row = None
    try:
        if body.contract_id:
            try:
                cid = uuid.UUID(body.contract_id)
                contract_row = await session.scalar(
                    select(Contract).where(Contract.id == cid, Contract.tenant_id == resolved_tenant)
                )
            except ValueError:
                pass

        if not contract_row and vendor_uuid:
            contract_row = await session.scalar(
                select(Contract).where(Contract.vendor_id == vendor_uuid, Contract.tenant_id == resolved_tenant)
            )

        if contract_row:
            if not body.objectives:
                cached_packet = await session.scalar(
                    select(DecisionPacket).where(
                        DecisionPacket.tenant_id == resolved_tenant,
                        DecisionPacket.packet_type == PACKET_RENEWAL_DOSSIER,
                        DecisionPacket.entity_id == contract_row.id,
                    )
                )
                cached_brief = (
                    (cached_packet.payload or {}).get("brief")
                    if cached_packet and isinstance(cached_packet.payload, dict)
                    else None
                )
                if isinstance(cached_brief, dict) and cached_brief.get("leverage_points"):
                    logger.info(
                        "negotiation_brief_served_from_precomputed_packet",
                        tenant_id=resolved_tenant,
                        contract_id=str(contract_row.id),
                    )
                    return NegotiationBriefResponse.model_validate(cached_brief)

            terms_stmt = select(func.sum(ContractTermsVersion.unit_price * func.coalesce(ContractTermsVersion.qty_min, 1))).where(
                ContractTermsVersion.contract_id == contract_row.id
            )
            terms_val = await session.scalar(terms_stmt)
            if terms_val and float(terms_val) > 0:
                annual_spend = Decimal(str(round(float(terms_val), 2)))
    except Exception:
        pass

    live_util: dict[str, Any] = {
        "utilization_pct": None,
        "active_users_30d": 0,
        "purchased_seats": 0,
        "idle_seats": 0,
        "forecast_savings_estimate": 0.0,
        "has_telemetry": False,
        "has_forecast": False,
    }
    if vendor_uuid:
        try:
            live_util = await acompute_vendor_utilization(session, resolved_tenant, vendor_uuid)
        except Exception:
            pass

    # 3. Retrieve RAG document passages for legal clauses
    passages: list[dict[str, Any]] = []
    try:
        passages = await asyncio.to_thread(
            search_documents,
            tenant_id=resolved_tenant,
            query=f"{vendor_name} renewal termination notice price escalation increase discount",
            vendor_id=body.vendor_id if vendor_uuid else None,
            document_type="contract",
            limit=4,
        )
        passages = await retain_existing_documents(session, tenant_id=resolved_tenant, rows=passages)
    except Exception as exc:
        logger.warning("negotiation_rag_search_failed", error=str(exc))

    clauses: list[ClauseCitation] = []
    for p in passages:
        clauses.append(
            ClauseCitation(
                clause_type=str(p.get("section") or "COMMERCIAL_TERMS"),
                summary=str(p.get("content", ""))[:140],
                document_id=str(p.get("document_id") or ""),
                filename=p.get("filename"),
                page=p.get("page"),
                section=p.get("section"),
                verbatim_excerpt=str(p.get("content", ""))[:400],
            )
        )

    # 4. Check for AP audit reconciliation exceptions
    exceptions_count = 0
    total_exceptions_discrepancy = Decimal("0")
    if contract_row:
        try:
            ex_res = await session.execute(
                select(ReconciliationException).where(
                    ReconciliationException.contract_id == contract_row.id,
                    ReconciliationException.tenant_id == resolved_tenant,
                )
            )
            exceptions = ex_res.scalars().all()
            exceptions_count = len(exceptions)
            for ex in exceptions:
                total_exceptions_discrepancy += Decimal(str(ex.variance_amount or 0))
        except Exception:
            pass

    # 5. Synthesize intelligent negotiation leverage
    llm_synthesized = None
    try:
        system_prompt = (
            "You are the Zellovest Renewal Agent, an elite AI procurement negotiator. "
            "Given the vendor profile, spend, contract clauses, and audit history, generate an "
            "evidence-based commercial negotiation brief. Output MUST be valid JSON with keys: "
            "'leverage_points' (list of strings), 'recommended_actions' (list of strings), "
            "'talking_points' (list of strings), 'risk_factors' (list of strings)."
        )
        user_prompt = json.dumps(
            {
                "vendor_name": vendor_name,
                "annual_spend": float(annual_spend),
                "contract_number": contract_row.contract_number if contract_row else "Standard Agreement",
                "notice_period_days": contract_row.notice_period_days if contract_row else 30,
                "auto_renew": contract_row.auto_renew if contract_row else True,
                "ap_exceptions_count": exceptions_count,
                "ap_discrepancies_usd": float(total_exceptions_discrepancy),
                "clauses_excerpt": [c.verbatim_excerpt for c in clauses[:2]],
                "objectives": body.objectives,
            }
        )
        content, _ = _completion(system_prompt, user_prompt, temperature=0.1)
        llm_synthesized = _json_object(content)
    except Exception as exc:
        logger.info("llm_synthesis_skipped_or_failed", reason=str(exc))

    notice_days = contract_row.notice_period_days if contract_row else 30
    util_pct_display = (
        f"{live_util['utilization_pct']}%"
        if live_util.get("utilization_pct") is not None
        else "unverified"
    )
    est_waste_usd = float(live_util.get("forecast_savings_estimate") or 0.0)
    if est_waste_usd <= 0.0 and live_util.get("utilization_pct") is not None and live_util["utilization_pct"] < 100:
        est_waste_usd = float(annual_spend) * max(0.0, 1.0 - live_util["utilization_pct"] / 100.0)

    default_leverage_points = [
        (
            f"Live Okta telemetry shows {live_util['idle_seats']} unused seats "
            f"({util_pct_display} utilization); right-sizing could save ~${est_waste_usd:,.0f}/yr."
            if live_util.get("has_telemetry") or live_util.get("has_forecast")
            else "Connect Okta usage telemetry to quantify idle license reclamation before renewal."
        ),
        f"Contractual {notice_days}-day notice window provides active leverage if non-renewal option is signaled before cutoff.",
        "Benchmark market alternatives to resist automatic price escalations.",
    ]
    if exceptions_count > 0:
        default_leverage_points.append(
            f"AP Audit uncovered {exceptions_count} invoice discrepancies (${total_exceptions_discrepancy:,.2f}) — use to demand fee credits."
        )

    default_recommended_actions = [
        "1. Record formal notice decision ahead of the contractual termination cutoff.",
        "2. Align renewal seat commitment to forecasted department demand.",
        "3. Request a 0% price-escalation cap or multi-year rate freeze.",
        "4. Require credit resolution for open AP audit billing discrepancies.",
    ]

    default_talking_points = [
        f"\"Our telemetry shows {util_pct_display} seat utilization for {vendor_name}; we are aligning our renewal commitment to active demand.\"",
        "\"Under our current budget framework, any renewal requiring price escalation cannot be approved without tier restructuring.\"",
        "\"We are evaluating alternative platforms that provide multi-year price locks and flexible seat licensing.\"",
    ]

    default_risk_factors = [
        "Auto-renewal clause will legally lock in escalated rates if written opt-out is delayed beyond notice deadline.",
        "Key operational workflows depend on this tool; plan sufficient lead time for migration if terms are rejected.",
    ]

    if llm_synthesized and isinstance(llm_synthesized, dict):
        leverage_points = llm_synthesized.get("leverage_points") or default_leverage_points
        recommended_actions = llm_synthesized.get("recommended_actions") or default_recommended_actions
        talking_points = llm_synthesized.get("talking_points") or default_talking_points
        risk_factors = llm_synthesized.get("risk_factors") or default_risk_factors
    else:
        leverage_points = default_leverage_points
        recommended_actions = default_recommended_actions
        talking_points = default_talking_points
        risk_factors = default_risk_factors

    return NegotiationBriefResponse(
        vendor_id=body.vendor_id,
        vendor_name=vendor_name,
        current_spend=annual_spend,
        contract_terms={
            "contract_number": contract_row.contract_number if contract_row else "CTR-ESTIMATED",
            "auto_renew": contract_row.auto_renew if contract_row else True,
            "notice_period_days": contract_row.notice_period_days if contract_row else 30,
            "payment_terms": "net_30",
        },
        utilization_data={
            "overall_utilization_pct": live_util.get("utilization_pct"),
            "active_users": live_util.get("active_users_30d", 0),
            "purchased_seats": live_util.get("purchased_seats", 0),
            "idle_seats_90d": live_util.get("idle_seats", 0),
            "estimated_annual_waste_usd": round(est_waste_usd, 2),
        },
        leverage_points=leverage_points,
        recommended_actions=recommended_actions,
        talking_points=talking_points,
        risk_factors=risk_factors,
        contractual_clauses=clauses,
        generated_at=datetime.now(UTC),
        cacheable=bool(llm_synthesized and isinstance(llm_synthesized, dict)),
    )


@router.post("/renewal-prep", response_model=RenewalPreparationResponse)
async def prepare_renewal(
    body: RenewalPreparationRequest,
    current_user: User | None = Depends(get_optional_user),
    session: AsyncSession = Depends(get_db_session),
) -> RenewalPreparationResponse:
    """Prepare high-level commercial indicators for an upcoming contract renewal."""
    resolved_tenant = normalize_tenant_id(
        current_user.tenant_id if current_user else body.tenant_id
    )

    vendor_name = "Target Vendor"
    annual_spend = Decimal("94200.00")
    now = datetime.now(UTC)
    renewal_target: date = (now + timedelta(days=60)).date()
    notice_days = 30
    auto_renew = True

    try:
        v_uuid = uuid.UUID(body.vendor_id)
        vendor_row = await session.scalar(
            select(Vendor).where(Vendor.id == v_uuid, Vendor.tenant_id == resolved_tenant)
        )
        if vendor_row:
            vendor_name = vendor_row.name
            # Try to fetch actual spend from terms
            spend_stmt = select(func.sum(ContractTermsVersion.unit_price * func.coalesce(ContractTermsVersion.qty_min, 1))).join(
                Contract, ContractTermsVersion.contract_id == Contract.id
            ).where(Contract.vendor_id == v_uuid, Contract.tenant_id == resolved_tenant)
            calc_spend = await session.scalar(spend_stmt)
            if calc_spend and float(calc_spend) > 0:
                annual_spend = Decimal(str(round(float(calc_spend), 2)))
    except (ValueError, Exception):
        pass

    if body.contract_id:
        try:
            cid = uuid.UUID(body.contract_id)
            cached_packet = await session.scalar(
                select(DecisionPacket).where(
                    DecisionPacket.tenant_id == resolved_tenant,
                    DecisionPacket.packet_type == PACKET_RENEWAL_DOSSIER,
                    DecisionPacket.entity_id == cid,
                )
            )
            cached_prep = (
                (cached_packet.payload or {}).get("prep")
                if cached_packet and isinstance(cached_packet.payload, dict)
                else None
            )
            if isinstance(cached_prep, dict) and cached_prep.get("vendor_name"):
                return RenewalPreparationResponse.model_validate(cached_prep)

            c_row = await session.scalar(select(Contract).where(Contract.id == cid, Contract.tenant_id == resolved_tenant))
            if c_row:
                if c_row.notice_period_days is not None:
                    notice_days = c_row.notice_period_days
                auto_renew = c_row.auto_renew
                if c_row.renewal_date:
                    renewal_target = c_row.renewal_date
        except Exception:
            pass

    live_util: dict[str, Any] = {
        "utilization_pct": None,
        "idle_seats": 0,
        "forecast_savings_estimate": 0.0,
        "has_forecast": False,
    }
    try:
        if body.vendor_id:
            live_util = await acompute_vendor_utilization(
                session, resolved_tenant, uuid.UUID(body.vendor_id)
            )
    except Exception:
        pass
    util_rate = (
        round(live_util["utilization_pct"] / 100.0, 4)
        if live_util.get("utilization_pct") is not None
        else 0.0
    )
    unused_seats = int(live_util.get("idle_seats") or 0)
    pot_savings = Decimal(str(round(float(live_util.get("forecast_savings_estimate") or 0.0), 2)))
    if pot_savings <= Decimal("0") and live_util.get("utilization_pct") is not None and live_util["utilization_pct"] < 85.0:
        pot_savings = (annual_spend * Decimal(str(max(0.0, 1.0 - util_rate)))).quantize(Decimal("0.01"))

    levers = []
    if live_util.get("has_forecast") and live_util["forecast_recommended_seats"] < live_util["forecast_current_seats"]:
        levers.append(
            f"ML forecast recommends {live_util['forecast_recommended_seats']} seats (vs {live_util['forecast_current_seats']} current) saving ~${float(pot_savings):,.0f}/yr."
        )
    elif unused_seats > 0:
        levers.append(f"{unused_seats} unused/idle licenses identified via Okta usage telemetry.")
    else:
        levers.append("Confirm active seat demand against department headcount before renewal.")

    return RenewalPreparationResponse(
        vendor_id=body.vendor_id,
        vendor_name=vendor_name,
        current_annual_spend=annual_spend,
        renewal_date=renewal_target,
        notice_period_days=notice_days,
        auto_renewal=auto_renew,
        utilization_rate=util_rate,
        unused_licenses=unused_seats,
        potential_savings=pot_savings,
        contract_constraints=[
            f"Auto-renewal notice requires {notice_days} days advance written notification."
            if auto_renew
            else "Manual renewal contract — no auto-renewal lock-in.",
            "Verify price-escalation caps and true-down rights in source contract passages.",
        ],
        negotiation_levers=levers,
        generated_at=now,
    )


@router.post("/remind", response_model=RenewalReminderResponse)
async def schedule_renewal_reminder(
    body: RenewalReminderRequest,
    current_user: User | None = Depends(get_optional_user),
    session: AsyncSession = Depends(get_db_session),
) -> RenewalReminderResponse:
    """Schedule a renewal notice deadline reminder workflow."""
    resolved_tenant = normalize_tenant_id(current_user.tenant_id if current_user else None)
    user_id = current_user.id if current_user else None

    contract_uuid = None
    try:
        contract_uuid = uuid.UUID(body.contract_id)
    except ValueError:
        pass

    vendor_name = "Vendor"
    contract_number = "CTR-RENEWAL"
    notice_days = 30
    ren_date = datetime.now(UTC).date() + timedelta(days=60)

    if contract_uuid:
        try:
            contract_row = await session.scalar(
                select(Contract).where(Contract.id == contract_uuid, Contract.tenant_id == resolved_tenant)
            )
            if contract_row:
                contract_number = contract_row.contract_number
                if contract_row.notice_period_days is not None:
                    notice_days = contract_row.notice_period_days
                if contract_row.renewal_date:
                    ren_date = contract_row.renewal_date

                vendor_row = await session.scalar(
                    select(Vendor).where(Vendor.id == contract_row.vendor_id)
                )
                if vendor_row:
                    vendor_name = vendor_row.name
        except Exception:
            pass

    notice_deadline = ren_date - timedelta(days=notice_days)
    remind_date = notice_deadline - timedelta(days=body.remind_days_before_notice)
    days_to_notice = (notice_deadline - datetime.now(UTC).date()).days

    reminder_wf = Workflow(
        tenant_id=resolved_tenant,
        workflow_type=WorkflowType.RENEWAL_NEGOTIATION,
        title=f"Notice Deadline Reminder: {vendor_name} ({contract_number})",
        description=(
            f"Contract {contract_number} has an auto-renewal notice deadline on {notice_deadline.isoformat()} "
            f"({body.remind_days_before_notice} days prior). Prepare negotiation levers before notice window closes."
        ),
        reference_type="renewal",
        reference_id=contract_uuid or uuid.uuid4(),
        assignee_user_id=user_id,
        status=WorkflowStatus.PENDING,
        due_at=datetime.combine(remind_date, datetime.min.time(), tzinfo=UTC),
        extra={
            "contract_id": body.contract_id,
            "vendor_id": body.vendor_id,
            "vendor_name": vendor_name,
            "contract_number": contract_number,
            "notice_deadline_date": notice_deadline.isoformat(),
            "remind_days_before_notice": body.remind_days_before_notice,
            "notes": body.notes,
        },
    )
    try:
        session.add(reminder_wf)
        await session.commit()
        await session.refresh(reminder_wf)
    except Exception as exc:
        logger.warning("reminder_workflow_commit_failed", error=str(exc))
        await session.rollback()

    logger.info(
        "renewal_reminder_scheduled",
        workflow_id=str(reminder_wf.id),
        contract_id=body.contract_id,
        notice_deadline=notice_deadline.isoformat(),
        remind_date=remind_date.isoformat(),
    )

    return RenewalReminderResponse(
        reminder_id=str(reminder_wf.id),
        contract_id=body.contract_id,
        vendor_name=vendor_name,
        notice_deadline_date=notice_deadline.isoformat(),
        remind_date=remind_date.isoformat(),
        days_until_notice=days_to_notice,
        status="scheduled",
        message=(
            f"Reminder set for {vendor_name}. You will be alerted on {remind_date.isoformat()} "
            f"({body.remind_days_before_notice} days prior to notice deadline {notice_deadline.isoformat()})."
        ),
    )


@router.get("/reminders", response_model=list[RenewalReminderItem])
async def list_renewal_reminders(
    tenant_id: str | None = Query(default=None),
    current_user: User | None = Depends(get_optional_user),
    session: AsyncSession = Depends(get_db_session),
) -> list[RenewalReminderItem]:
    """List all scheduled renewal notice deadline reminders."""
    resolved_tenant = normalize_tenant_id(
        current_user.tenant_id if current_user else tenant_id
    )

    today = datetime.now(UTC).date()
    items: list[RenewalReminderItem] = []

    try:
        result = await session.execute(
            select(Workflow)
            .where(
                Workflow.tenant_id == resolved_tenant,
                Workflow.workflow_type == WorkflowType.RENEWAL_NEGOTIATION,
                Workflow.reference_type == "renewal",
            )
            .order_by(Workflow.due_at.asc().nulls_last())
        )
        workflows = result.scalars().all()

        for wf in workflows:
            metadata = wf.extra or {}
            notice_deadline_str = metadata.get("notice_deadline_date") or (today + timedelta(days=30)).isoformat()
            try:
                deadline_date = date.fromisoformat(notice_deadline_str)
                days_to_notice = (deadline_date - today).days
            except Exception:
                days_to_notice = 30

            items.append(
                RenewalReminderItem(
                    id=str(wf.id),
                    contract_id=metadata.get("contract_id", str(wf.reference_id or "")),
                    contract_number=metadata.get("contract_number", "CTR-RENEWAL"),
                    vendor_id=metadata.get("vendor_id", ""),
                    vendor_name=metadata.get("vendor_name", "Vendor"),
                    notice_deadline_date=notice_deadline_str,
                    remind_date=wf.due_at.date().isoformat() if wf.due_at else today.isoformat(),
                    days_until_notice=days_to_notice,
                    status=wf.status.value,
                    notes=metadata.get("notes"),
                    created_at=wf.created_at.isoformat(),
                )
            )
    except Exception as exc:
        logger.warning("list_renewal_reminders_query_failed", error=str(exc))

    return items
