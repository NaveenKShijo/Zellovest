"""Tests for pre-computed decision packets, live utilization, workflows, and decision feed."""

from __future__ import annotations

import base64
import os
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session, sessionmaker

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://localhost/zellovest")
os.environ.setdefault("ASYNC_DATABASE_URL", "postgresql+asyncpg://localhost/zellovest")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("RAMP_CLIENT_ID", "test-id")
os.environ.setdefault("RAMP_CLIENT_SECRET", "test-secret")
os.environ.setdefault("RAMP_AUTH_URL", "https://app.ramp.com/v1/authorize")
os.environ.setdefault("RAMP_TOKEN_URL", "https://api.ramp.com/developer/v1/token")
os.environ.setdefault("RAMP_API_BASE_URL", "https://api.ramp.com/developer/v1")
os.environ.setdefault("RAMP_REDIRECT_URI", "http://localhost:8000/callback")
os.environ.setdefault("RAMP_WEBHOOK_SECRET", "whsec-test")
os.environ.setdefault("CREDENTIALS_ENCRYPTION_KEY", base64.b64encode(os.urandom(32)).decode())
os.environ.setdefault("GCS_RAW_BUCKET", "tenant-bucket")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret")

from zellovest_procurement.api.deps import get_db_session, get_optional_user
from zellovest_procurement.main import create_app
from zellovest_shared.db.base import Base
from zellovest_shared.db.core import Department, Employee, Vendor
from zellovest_shared.db.intelligence import (
    AlertStatus,
    DecisionPacket,
    ExceptionRule,
    ExceptionStatus,
    LicenseAssignment,
    MaverickAlert,
    ReconciliationException,
    SavingsKind,
    SavingsLedgerEntry,
    SeatForecast,
    UsageEvent,
    Workflow,
    WorkflowStatus,
)
from zellovest_shared.db.models import User
from zellovest_shared.db.transact import (
    CardTransaction,
    Contract,
    ContractChangeType,
    ContractLine,
    ContractStatus,
    ContractTermsVersion,
    ContractVersion,
    DocStatus,
    DocType,
    Document,
    Invoice,
    InvoiceLineItem,
)
from zellovest_shared.decision_packets import (
    ENTITY_CONTRACT,
    ENTITY_EXCEPTION,
    ENTITY_MAVERICK_ALERT,
    build_ap_investigation_packet_sync,
    build_maverick_review_packet_sync,
    build_renewal_dossier_packet_sync,
    refresh_tenant_decision_packets_sync,
)
from zellovest_workers.celery_app import celery_app


@pytest.fixture
def sync_session() -> Session:
    """In-memory SQLite session for synchronous packet builder tests."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    sess = factory()
    yield sess
    sess.close()


def _seed_tenant_data(session: Session, tenant_id: str) -> dict[str, uuid.UUID]:
    """Seed vendor, contract, invoice exception, usage, forecast, and maverick alert."""
    now = datetime.now(UTC)
    today = now.date()

    vendor = Vendor(id=uuid.uuid4(), tenant_id=tenant_id, name="Acme Cloud")
    dept = Department(id=uuid.uuid4(), tenant_id=tenant_id, name="Engineering")
    emp1 = Employee(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        department_id=dept.id,
        first_name="Ada",
        last_name="Lovelace",
        email="ada@acme.test",
    )
    emp2 = Employee(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        department_id=dept.id,
        first_name="Alan",
        last_name="Turing",
        email="alan@acme.test",
    )
    session.add_all([vendor, dept, emp1, emp2])
    session.flush()

    doc_contract = Document(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        vendor_id=vendor.id,
        filename="acme_msa.pdf",
        document_type=DocType.CONTRACT,
        status=DocStatus.EXTRACTED,
        gcs_key=f"{tenant_id}/contracts/acme_msa.pdf",
        mime_type="application/pdf",
    )
    doc_invoice = Document(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        vendor_id=vendor.id,
        filename="acme_inv_100.pdf",
        document_type=DocType.INVOICE,
        status=DocStatus.EXTRACTED,
        gcs_key=f"{tenant_id}/invoices/acme_inv_100.pdf",
        mime_type="application/pdf",
    )
    session.add_all([doc_contract, doc_invoice])
    session.flush()

    contract = Contract(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        vendor_id=vendor.id,
        document_id=doc_contract.id,
        contract_number="MSA-ACME-01",
        title="Acme Enterprise Plan",
        start_date=today - timedelta(days=300),
        end_date=today + timedelta(days=50),
        renewal_date=today + timedelta(days=50),
        notice_period_days=30,
        auto_renew=True,
        status=ContractStatus.ACTIVE,
    )
    session.add(contract)
    session.flush()

    version = ContractVersion(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        contract_id=contract.id,
        version_no=1,
        change_type=ContractChangeType.ORIGINAL,
        effective_from=today - timedelta(days=300),
    )
    line = ContractLine(id=uuid.uuid4(), tenant_id=tenant_id, contract_id=contract.id)
    session.add_all([version, line])
    session.flush()

    term = ContractTermsVersion(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        contract_id=contract.id,
        contract_version_id=version.id,
        contract_line_id=line.id,
        version_no=1,
        line_no=1,
        product_code="ACME-PRO",
        description="Acme Pro Seat",
        unit_price=Decimal("100.00"),
        currency="USD",
        qty_min=Decimal("10"),
        qty_max=Decimal("100"),
        effective_from=today - timedelta(days=300),
    )
    session.add(term)
    session.flush()

    invoice = Invoice(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        vendor_id=vendor.id,
        contract_id=contract.id,
        document_id=doc_invoice.id,
        invoice_number="INV-100",
        invoice_date=now,
        due_date=now + timedelta(days=30),
        subtotal=Decimal("1200.00"),
        tax_amount=Decimal("0.00"),
        total_amount=Decimal("1200.00"),
        currency="USD",
        status="flagged",
        extra={"commercial_reconciled_at": now.isoformat()},
    )
    session.add(invoice)
    session.flush()

    inv_line = InvoiceLineItem(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        invoice_id=invoice.id,
        line_no=1,
        product_code="ACME-PRO",
        description="Acme Pro Seat",
        quantity=Decimal("10"),
        unit_price=Decimal("120.00"),
        total=Decimal("1200.00"),
    )
    session.add(inv_line)
    session.flush()

    exc = ReconciliationException(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        invoice_id=invoice.id,
        invoice_line_id=inv_line.id,
        contract_id=contract.id,
        contract_version_id=version.id,
        contract_term_id=term.id,
        rule_type=ExceptionRule.PRICE,
        expected_value=Decimal("100.00"),
        billed_value=Decimal("120.00"),
        variance_amount=Decimal("200.00"),
        variance_pct=20.0,
        severity="high",
        status=ExceptionStatus.OPEN,
    )
    session.add(exc)

    # Live Okta assignments + 1 active usage event (50% utilization across 2 seats)
    session.add_all(
        [
            LicenseAssignment(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                employee_id=emp1.id,
                vendor_id=vendor.id,
                seats=1,
                status="active",
            ),
            LicenseAssignment(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                employee_id=emp2.id,
                vendor_id=vendor.id,
                seats=1,
                status="active",
            ),
            UsageEvent(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                employee_id=emp1.id,
                vendor_id=vendor.id,
                event_type="user.authentication.sso",
                occurred_at=now - timedelta(days=5),
                okta_event_id="evt-1",
            ),
            SeatForecast(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                vendor_id=vendor.id,
                department_id=dept.id,
                department="Engineering",
                forecast_date=today,
                horizon_days=60,
                current_seats=10,
                recommended_seats=7,
                confidence=Decimal("0.9200"),
                shelfware_amount=Decimal("300.00"),
                trueup_risk_amount=Decimal("50.00"),
                savings_estimate=Decimal("250.00"),
                model_version="v1",
            ),
        ]
    )

    txn = CardTransaction(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        employee_id=emp1.id,
        department_id=dept.id,
        vendor_id=vendor.id,
        merchant_name="Cursor",
        amount=Decimal("40.00"),
        currency="USD",
        state="CLEARED",
        is_recurring=True,
        txn_date=now,
        external_id="ramp-txn-1",
    )
    session.add(txn)
    session.flush()

    alert = MaverickAlert(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        transaction_id=txn.id,
        employee_id=emp1.id,
        merchant_name="Cursor",
        jev_is_saas_score=Decimal("0.9600"),
        jev_review_score=Decimal("0.9100"),
        status=AlertStatus.OPEN,
        overlap_contract_id=contract.id,
        overlap_contract_term_id=term.id,
        overlap_score=Decimal("0.9100"),
        recommended_action="Consolidate to Acme Pro Seat.",
    )
    session.add(alert)
    session.commit()

    return {
        "vendor_id": vendor.id,
        "contract_id": contract.id,
        "doc_contract_id": doc_contract.id,
        "invoice_id": invoice.id,
        "exception_id": exc.id,
        "alert_id": alert.id,
    }


def test_precomputed_decision_packets_and_live_utilization(sync_session: Session) -> None:
    """AP, renewal, and maverick packets compute deterministic outcomes with citations."""
    tenant_id = "tenant-packet-test"
    ids = _seed_tenant_data(sync_session, tenant_id)

    def fake_rag(**kwargs):  # type: ignore[no-untyped-def]
        return [
            {
                "chunk_id": "chk-1",
                "document_id": str(ids["doc_contract_id"]),
                "filename": "acme_msa.pdf",
                "page": 4,
                "section": "Pricing & Escalation",
                "content": "Annual price increases shall not exceed 0%.",
            }
        ]

    ap_pkt = build_ap_investigation_packet_sync(
        sync_session, tenant_id, ids["exception_id"], rag_search=fake_rag
    )
    assert ap_pkt is not None
    assert float(ap_pkt.financial_impact or 0) == 200.0
    assert len(ap_pkt.payload["confirmed_facts"]) >= 2
    assert len(ap_pkt.payload["calculated_values"]) >= 1
    assert any(c.get("page") == 4 for c in ap_pkt.payload["citations"])

    # Idempotent when source hasn't changed
    ap_pkt_again = build_ap_investigation_packet_sync(
        sync_session, tenant_id, ids["exception_id"], rag_search=fake_rag
    )
    assert ap_pkt_again is not None
    assert ap_pkt_again.id == ap_pkt.id

    ren_pkt = build_renewal_dossier_packet_sync(
        sync_session, tenant_id, ids["contract_id"], rag_search=fake_rag
    )
    assert ren_pkt is not None
    assert ren_pkt.payload["utilization"]["utilization_pct"] == 50.0
    assert ren_pkt.payload["utilization"]["forecast_recommended_seats"] == 7
    assert any("200.00" in pt for pt in ren_pkt.payload["brief"]["leverage_points"])

    mav_pkt = build_maverick_review_packet_sync(sync_session, tenant_id, ids["alert_id"])
    assert mav_pkt is not None
    assert float(mav_pkt.financial_impact or 0) == 480.0
    assert "Slack" not in (mav_pkt.recommended_action or "")
    assert "email" not in (mav_pkt.recommended_action or "").lower()

    counts = refresh_tenant_decision_packets_sync(sync_session, tenant_id)
    assert counts["ap_investigation"] >= 1
    assert counts["renewal_dossier"] >= 1
    assert counts["maverick_review"] >= 1


def test_celery_beat_automations_registered() -> None:
    """Celery Beat includes scheduled ingestion, Drive watch renewal, and packet sweep."""
    schedule = celery_app.conf.beat_schedule
    assert "scheduled-integrations-sync" in schedule
    assert "renew-expiring-drive-watches" in schedule
    assert "refresh-decision-packets-hourly" in schedule
    assert "scan-renewal-notice-deadlines" in schedule


@pytest.mark.asyncio
async def test_workflows_and_decision_feed_end_to_end(tmp_path, monkeypatch) -> None:
    """Decision feed actions and real DB workflows execute end to end without external alerts."""
    monkeypatch.setattr(
        "zellovest_shared.decision_packets._safe_rag_search",
        lambda **_kwargs: [],
    )
    db_file = tmp_path / "test_feed.db"
    sync_url = f"sqlite:///{db_file}"
    async_url = f"sqlite+aiosqlite:///{db_file}"

    sync_engine = create_engine(sync_url)
    Base.metadata.create_all(sync_engine)
    SyncFactory = sessionmaker(bind=sync_engine, expire_on_commit=False)

    tenant_id = "tenant-e2e-feed"
    user_id = uuid.uuid4()
    with SyncFactory() as sess:
        sess.add(
            User(
                id=user_id,
                email="buyer@acme.test",
                name="Buyer",
                password_hash="hash",
                role="procurement_member",
                tenant_id=tenant_id,
                is_active=True,
            )
        )
        ids = _seed_tenant_data(sess, tenant_id)
    sync_engine.dispose()

    async_engine = create_async_engine(async_url)
    AsyncFactory = async_sessionmaker(async_engine, expire_on_commit=False, class_=AsyncSession)

    app = create_app()

    async def override_db():
        async with AsyncFactory() as session:
            yield session

    fake_user = User(
        id=user_id,
        email="buyer@acme.test",
        name="Buyer",
        password_hash="hash",
        role="procurement_member",
        tenant_id=tenant_id,
        is_active=True,
    )
    app.dependency_overrides[get_db_session] = override_db
    app.dependency_overrides[get_optional_user] = lambda: fake_user

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # 1. Auto-hydrate decision feed on first GET
        feed_res = await client.get("/api/v1/decision-feed")
        assert feed_res.status_code == 200, feed_res.text
        feed = feed_res.json()
        assert feed["summary"]["pending_count"] == 3
        assert len(feed["items"]) == 3

        # 2. Fetch packet by entity
        by_ent = await client.get(
            f"/api/v1/decision-feed/by-entity?entity_type={ENTITY_EXCEPTION}&entity_id={ids['exception_id']}"
        )
        assert by_ent.status_code == 200
        ap_packet_id = by_ent.json()["id"]

        # 3. Resolve AP exception -> stages overbill HARD_CASH savings
        act_ap = await client.post(
            f"/api/v1/decision-feed/{ap_packet_id}/action",
            json={"action": "resolve"},
        )
        assert act_ap.status_code == 200, act_ap.text
        assert act_ap.json()["savings_entry_id"] is not None

        # 4. Mark Maverick migrated -> stages AVOIDANCE savings
        mav_pkt = next(i for i in feed["items"] if i["entity_type"] == ENTITY_MAVERICK_ALERT)
        act_mav = await client.post(
            f"/api/v1/decision-feed/{mav_pkt['id']}/action",
            json={"action": "mark_migrated"},
        )
        assert act_mav.status_code == 200, act_mav.text
        assert act_mav.json()["savings_entry_id"] is not None

        # 5. Create in-app workflow from renewal dossier
        ren_pkt = next(i for i in feed["items"] if i["entity_type"] == ENTITY_CONTRACT)
        act_ren = await client.post(
            f"/api/v1/decision-feed/{ren_pkt['id']}/action",
            json={"action": "create_workflow"},
        )
        assert act_ren.status_code == 200, act_ren.text
        wf_id = act_ren.json()["workflow_id"]
        assert wf_id is not None

        # 6. List and approve workflow via /api/v1/workflows
        wf_list = await client.get("/api/v1/workflows")
        assert wf_list.status_code == 200
        assert wf_list.json()["total"] == 1

        wf_approve = await client.post(
            f"/api/v1/workflows/{wf_id}/action",
            json={"action": "approve", "comment": "Approved in test"},
        )
        assert wf_approve.status_code == 200
        assert wf_approve.json()["status"] == "approved"

    async with AsyncFactory() as verify_sess:
        savings = (
            await verify_sess.execute(
                select(SavingsLedgerEntry).where(SavingsLedgerEntry.tenant_id == tenant_id)
            )
        ).scalars().all()
        assert len(savings) == 2
        kinds = {s.kind for s in savings}
        assert SavingsKind.HARD_CASH in kinds
        assert SavingsKind.AVOIDANCE in kinds

        wf_row = await verify_sess.scalar(
            select(Workflow).where(Workflow.tenant_id == tenant_id)
        )
        assert wf_row is not None
        assert wf_row.status == WorkflowStatus.APPROVED

    await async_engine.dispose()
