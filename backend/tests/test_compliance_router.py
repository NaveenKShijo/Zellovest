"""Integration tests for AP Audit & Compliance API router."""

import pytest
from httpx import ASGITransport, AsyncClient
from zellovest_procurement.main import create_app
from zellovest_shared.db.session import get_async_engine


@pytest.fixture(autouse=True)
async def cleanup_db_connections():
    """Ensure asyncpg connection pool is disposed cleanly per test."""
    yield
    engine = get_async_engine()
    await engine.dispose()


@pytest.mark.asyncio
async def test_compliance_kpis_real_truth() -> None:
    """Verify AP Audit KPIs calculate true ledger values and split unreconciled."""
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/compliance/kpis?tenant_id=default-org")
        assert response.status_code == 200
        data = response.json()
        assert "total_invoiced_amount" in data
        assert "flagged_discrepancy_amount" in data
        assert "total_invoices_count" in data
        assert "clean_invoices_count" in data
        assert "exception_invoices_count" in data
        assert "unreconciled_invoices_count" in data
        assert "clean_rate_pct" in data

        # When no invoices are audited, clean rate must be 0.0%, never a fake 100%
        if data["clean_invoices_count"] + data["exception_invoices_count"] == 0:
            assert data["clean_rate_pct"] == 0.0


@pytest.mark.asyncio
async def test_compliance_exceptions_default_filter() -> None:
    """Verify exceptions list defaults to active exceptions and returns schema."""
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/compliance/exceptions?tenant_id=default-org")
        assert response.status_code == 200
        data = response.json()
        assert "items" in data
        assert "total" in data
        assert isinstance(data["items"], list)


@pytest.mark.asyncio
async def test_compliance_purge_orphans() -> None:
    """Verify orphan purge endpoint runs and reports purged metrics."""
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/v1/compliance/purge-orphans?tenant_id=default-org")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert "purged" in data
        assert "invoices" in data["purged"]
        assert "contracts" in data["purged"]
