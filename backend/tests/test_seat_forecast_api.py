"""Tests for the tenant-scoped forecast portfolio endpoint."""

from datetime import UTC, date, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import HTTPException

from zellovest_agentic.api.routers.negotiation import list_seat_forecasts


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
    assert "tenant-one" in session.execute.call_args.args[0].compile().params.values()
    assert "renewal_date" not in data[0]


@pytest.mark.asyncio
async def test_forecast_database_error_is_reported():
    """A database failure is never represented as an empty portfolio."""
    session = SimpleNamespace(execute=AsyncMock(side_effect=RuntimeError("database down")))
    with pytest.raises(HTTPException) as error:
        await list_seat_forecasts(SimpleNamespace(tenant_id="tenant-one"), session)
    assert error.value.status_code == 503
