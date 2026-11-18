"""Tests for Negotiation Agent and Renewal Notice Deadlines in Agentic Reasoning Service."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
import uuid
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from zellovest_agentic.api.deps import get_current_user
from zellovest_agentic.main import create_app
from zellovest_shared.db.core import Vendor
from zellovest_shared.db.intelligence import Workflow, WorkflowType
from zellovest_shared.db.models import User
from zellovest_shared.db.session import get_async_engine
from zellovest_shared.db.transact import (
    Contract,
    ContractChangeType,
    ContractLine,
    ContractStatus,
    ContractTermsVersion,
    ContractVersion,
)
from zellovest_workers.tasks.renewal_reminders import scan_notice_deadlines_sync

TEST_TENANT_ID = "test-renewals-fixture-org"


@pytest.fixture(autouse=True)
async def cleanup_db_connections():
    """Ensure asyncpg connection pool is disposed cleanly per test on Windows."""
    yield
    try:
        engine = get_async_engine()
        await engine.dispose()
    except Exception:
        pass


@pytest.fixture
def fake_user() -> User:
    """Create a mock authenticated procurement user for an isolated test tenant."""
    return User(
        id=uuid.uuid4(),
        email="procurement@test-zellovest.ai",
        tenant_id=TEST_TENANT_ID,
        role="procurement_member",
        is_active=True,
    )


@pytest.fixture
async def seed_test_contracts():
    """Seed isolated temporary test contracts for the test tenant and tear down afterwards."""
    engine = get_async_engine()
    now_dt = datetime.now(UTC)
    today = now_dt.date()

    vendor_id = uuid.uuid4()
    contract_id = uuid.uuid4()
    version_id = uuid.uuid4()
    line_id = uuid.uuid4()
    term_id = uuid.uuid4()

    start_d = today - timedelta(days=340)
    renewal_d = today + timedelta(days=25)

    async with AsyncSession(engine) as session:
        vendor = Vendor(
            id=vendor_id,
            tenant_id=TEST_TENANT_ID,
            name="Adobe Test Inc.",
            domain="adobe-test.com",
            category="Design & Creativity",
            payment_terms="Net 30",
            status="active",
            is_active=True,
        )
        session.add(vendor)
        await session.flush()

        contract = Contract(
            id=contract_id,
            tenant_id=TEST_TENANT_ID,
            vendor_id=vendor_id,
            contract_number="CTR-TEST-ADOBE-001",
            title="Adobe Creative Cloud Test Agreement",
            status=ContractStatus.ACTIVE,
            start_date=start_d,
            end_date=renewal_d,
            renewal_date=renewal_d,
            notice_period_days=30,
            auto_renew=True,
            termination_clause="30 days written notice required prior to renewal.",
        )
        session.add(contract)

        c_ver = ContractVersion(
            id=version_id,
            tenant_id=TEST_TENANT_ID,
            contract_id=contract_id,
            version_no=1,
            change_type=ContractChangeType.ORIGINAL,
            effective_from=start_d,
            effective_to=renewal_d,
            title="Adobe Creative Cloud Test Agreement",
            contract_start_date=start_d,
            contract_end_date=renewal_d,
            renewal_date=renewal_d,
            notice_period_days=30,
            auto_renew=True,
            termination_clause="30 days written notice required prior to renewal.",
        )
        session.add(c_ver)

        c_line = ContractLine(
            id=line_id,
            tenant_id=TEST_TENANT_ID,
            contract_id=contract_id,
        )
        session.add(c_line)
        await session.flush()

        c_terms = ContractTermsVersion(
            id=term_id,
            tenant_id=TEST_TENANT_ID,
            contract_id=contract_id,
            contract_version_id=version_id,
            contract_line_id=line_id,
            version_no=1,
            line_no=1,
            product_code="SKU-TEST-ADOBE-001",
            description="Adobe Creative Cloud Test Agreement",
            unit_price=Decimal("945.00"),
            currency="USD",
            qty_min=Decimal("100"),
            qty_max=Decimal("100"),
            effective_from=start_d,
            effective_to=renewal_d,
        )
        session.add(c_terms)
        await session.commit()

    yield {"vendor_id": vendor_id, "contract_id": contract_id}

    # Teardown
    async with AsyncSession(engine) as session:
        await session.execute(
            delete(ContractTermsVersion).where(ContractTermsVersion.contract_id == contract_id)
        )
        await session.execute(
            delete(ContractLine).where(ContractLine.contract_id == contract_id)
        )
        await session.execute(
            delete(ContractVersion).where(ContractVersion.contract_id == contract_id)
        )
        await session.execute(
            delete(Contract).where(Contract.id == contract_id)
        )
        await session.execute(
            delete(Vendor).where(Vendor.id == vendor_id)
        )
        await session.commit()


@pytest.mark.asyncio
async def test_list_upcoming_renewals(fake_user: User, seed_test_contracts):
    """Upcoming renewals endpoint returns countdown cards with notice deadlines."""
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: fake_user

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/negotiation/upcoming-renewals")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) > 0

        first = data[0]
        assert "contract_number" in first
        assert "vendor_name" in first
        assert "renewal_date" in first
        assert "notice_deadline_date" in first
        assert "days_until_notice_deadline" in first
        assert "badge" in first
        assert first["badge"] in {"30d", "60d", "90d", "120d", "future"}
        assert "key_leverage_points" in first
        assert isinstance(first["key_leverage_points"], list)


@pytest.mark.asyncio
async def test_list_upcoming_renewals_filter(fake_user: User, seed_test_contracts):
    """Filters by urgency badge, search string, and auto-renew status."""
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: fake_user

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Filter by 30d
        res_30d = await client.get("/api/v1/negotiation/upcoming-renewals?badge=30d")
        assert res_30d.status_code == 200
        for item in res_30d.json():
            assert item["badge"] == "30d"

        # Filter by search
        res_search = await client.get("/api/v1/negotiation/upcoming-renewals?search=Adobe")
        assert res_search.status_code == 200
        for item in res_search.json():
            assert "adobe" in item["vendor_name"].lower() or "adobe" in item["product_name"].lower()


@pytest.mark.asyncio
async def test_negotiation_brief_generation(fake_user: User):
    """Generates an evidence-backed negotiation brief for a vendor."""
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: fake_user

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/v1/negotiation/brief",
            json={
                "tenant_id": TEST_TENANT_ID,
                "vendor_id": str(uuid.uuid4()),
                "objectives": ["cap price escalation to 0%", "reduce unused seats by 20%"],
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert "vendor_name" in data
        assert "current_spend" in data
        assert "leverage_points" in data
        assert len(data["leverage_points"]) > 0
        assert "talking_points" in data
        assert len(data["talking_points"]) > 0
        assert "recommended_actions" in data
        assert len(data["recommended_actions"]) > 0
        assert "risk_factors" in data
        assert len(data["risk_factors"]) > 0


@pytest.mark.asyncio
async def test_renewal_prep_endpoint(fake_user: User):
    """Renewal prep provides key commercial metrics and potential savings."""
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: fake_user

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/v1/negotiation/renewal-prep",
            json={
                "tenant_id": TEST_TENANT_ID,
                "vendor_id": str(uuid.uuid4()),
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert "current_annual_spend" in data
        assert "potential_savings" in data
        assert "utilization_rate" in data
        assert "contract_constraints" in data
        assert "negotiation_levers" in data


@pytest.mark.asyncio
async def test_schedule_and_list_renewal_reminder(fake_user: User):
    """Schedule a proactive notice deadline reminder workflow."""
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: fake_user

    dummy_contract_id = str(uuid.uuid4())
    dummy_vendor_id = str(uuid.uuid4())

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Schedule reminder
        create_res = await client.post(
            "/api/v1/negotiation/remind",
            json={
                "contract_id": dummy_contract_id,
                "vendor_id": dummy_vendor_id,
                "remind_days_before_notice": 15,
                "notes": "Notify Marcus to draft opt-out letter",
            },
        )
        assert create_res.status_code == 200
        created = create_res.json()
        assert created["status"] == "scheduled"
        assert "notice_deadline_date" in created
        assert "remind_date" in created

        # List reminders
        list_res = await client.get("/api/v1/negotiation/reminders")
        assert list_res.status_code == 200
        reminders = list_res.json()
        assert isinstance(reminders, list)


@pytest.mark.asyncio
async def test_mcp_tool_find_renewals(fake_user: User, seed_test_contracts):
    """MCP find_renewals tool call returns renewal items."""
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: fake_user

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.post(
            "/api/v1/tools/call",
            json={
                "tool_name": "find_renewals",
                "tenant_id": TEST_TENANT_ID,
                "arguments": {"days_ahead": 90},
            },
        )
        assert res.status_code == 200
        data = res.json()
        assert data["success"] is True
        assert "renewals" in data["result"]
        assert len(data["result"]["renewals"]) > 0


def test_scan_notice_deadlines_worker_task():
    """Worker task scans contracts and handles notice countdowns gracefully."""
    result = scan_notice_deadlines_sync()
    assert "scanned" in result
    assert "reminders_created" in result
    assert isinstance(result["scanned"], int)
    assert isinstance(result["reminders_created"], int)
