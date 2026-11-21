"""Tests for the tenant-scoped forecast portfolio endpoint."""

from collections.abc import Iterator
from datetime import UTC, date, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from zellovest_agentic.api.deps import get_current_user, get_db_session
from zellovest_agentic.api.routers.negotiation import list_seat_forecasts, router
from zellovest_shared.db.core import Vendor
from zellovest_shared.db.intelligence import SeatForecast


@pytest.mark.asyncio
async def test_returns_persisted_cohort_and_scopes_query():
    """The endpoint preserves persisted data and filters by the authenticated tenant."""
    forecast = SimpleNamespace(
        id=uuid4(), vendor_id=uuid4(), department="Design", forecast_date=date(2026, 11, 21),
        created_at=datetime(2026, 11, 21, tzinfo=UTC), current_seats=100,
        recommended_seats=80, retention_curve={"horizon_days": 90}, confidence=0.8,
        shelfware_amount=10, trueup_risk_amount=20, savings_estimate=30,
        model_version="v1",
    )
    session = SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(
        all=lambda: [(forecast, "Vendor")]
    )))
    data = await list_seat_forecasts(SimpleNamespace(tenant_id="tenant-one"), session)
    assert data[0]["retention_curve"]["horizon_days"] == 90
    assert data[0]["recommended_seats"] == 80
    assert ["tenant-one"] in session.execute.call_args.args[0].compile().params.values()
    assert "renewal_date" not in data[0]


@pytest.mark.asyncio
async def test_forecast_database_error_is_reported():
    """A database failure is never represented as an empty portfolio."""
    session = SimpleNamespace(execute=AsyncMock(side_effect=RuntimeError("database down")))
    with pytest.raises(HTTPException) as error:
        await list_seat_forecasts(SimpleNamespace(tenant_id="tenant-one"), session)
    assert error.value.status_code == 503


@pytest.fixture
def forecast_session() -> Iterator[Session]:
    """Seed both default spellings and a separate organization in a real SQL database."""
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Vendor.__table__.create(engine)
    SeatForecast.__table__.create(engine)
    try:
        with Session(engine) as session:
            for tenant, name in (
                ("default_org", "Salesforce"),
                ("default-org", "Zoom"),
                ("other-org", "Private vendor"),
            ):
                vendor = Vendor(id=uuid4(), tenant_id=tenant, name=name)
                session.add(vendor)
                session.flush()
                session.add(SeatForecast(
                    id=uuid4(), tenant_id=tenant, vendor_id=vendor.id,
                    department="Sales", forecast_date=date(2026, 11, 21),
                    current_seats=99, recommended_seats=12,
                    retention_curve={"horizon_days": 120, "expected_demand": 11.322213},
                    confidence=0.9612, shelfware_amount=1292.70,
                    trueup_risk_amount=109.03, savings_estimate=156490.97,
                    model_version="v_test",
                ))
            session.commit()
            yield session
    finally:
        engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("tenant_id", ["default-org", "default_org", "default"])
async def test_frontend_receives_default_organization_forecasts(
    forecast_session: Session, tenant_id: str,
) -> None:
    """The frontend's authenticated URL returns underscore and hyphen forecast rows."""
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(tenant_id=tenant_id)
    app.dependency_overrides[get_db_session] = lambda: SimpleNamespace(
        execute=AsyncMock(side_effect=forecast_session.execute),
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/negotiation/seat-forecasts")
    assert response.status_code == 200
    forecasts = response.json()
    assert {row["vendor_name"] for row in forecasts} == {"Salesforce", "Zoom"}
    salesforce = next(row for row in forecasts if row["vendor_name"] == "Salesforce")
    assert salesforce["current_seats"] == 99
    assert salesforce["recommended_seats"] == 12
    assert float(salesforce["confidence"]) == 0.9612
    assert float(salesforce["savings_estimate"]) == 156490.97
    assert salesforce["retention_curve"]["horizon_days"] == 120


@pytest.mark.asyncio
async def test_default_alias_support_preserves_other_tenant_boundaries(
    forecast_session: Session,
) -> None:
    """Other organizations cannot read default forecasts, even using a query parameter."""
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(tenant_id="other-org")
    app.dependency_overrides[get_db_session] = lambda: SimpleNamespace(
        execute=AsyncMock(side_effect=forecast_session.execute),
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/negotiation/seat-forecasts?tenant_id=default_org")
    assert response.status_code == 200
    assert [row["vendor_name"] for row in response.json()] == ["Private vendor"]


@pytest.mark.asyncio
@pytest.mark.parametrize("vendor_tenant", [None, "other-org"])
async def test_vendor_metadata_does_not_hide_forecasts_or_cross_tenants(
    forecast_session: Session, vendor_tenant: str | None,
) -> None:
    """A missing or foreign vendor name cannot hide a valid forecast or leak metadata."""
    vendor_id = uuid4()
    if vendor_tenant:
        forecast_session.add(Vendor(
            id=vendor_id, tenant_id=vendor_tenant, name="Foreign vendor name",
        ))
        forecast_session.flush()
    forecast_session.add(SeatForecast(
        id=uuid4(), tenant_id="default_org", vendor_id=vendor_id,
        department="Marketing", forecast_date=date(2026, 11, 21),
        current_seats=84, recommended_seats=11,
    ))
    forecast_session.commit()
    session = SimpleNamespace(execute=AsyncMock(side_effect=forecast_session.execute))
    forecasts = await list_seat_forecasts(SimpleNamespace(tenant_id="default-org"), session)
    forecast = next(row for row in forecasts if row["vendor_id"] == str(vendor_id))
    assert forecast["recommended_seats"] == 11
    assert forecast["vendor_name"] == f"Vendor {vendor_id}"
