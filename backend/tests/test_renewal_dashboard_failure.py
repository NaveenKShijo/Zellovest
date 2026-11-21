"""Ensure renewal data failures do not appear as a clear dashboard."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from zellovest_agentic.api.routers.negotiation import list_upcoming_renewals


@pytest.mark.asyncio
async def test_renewal_database_failure_is_not_an_empty_list():
    """A failed query must be distinguishable from having no renewals."""
    session = SimpleNamespace(execute=AsyncMock(side_effect=RuntimeError("offline")))
    with pytest.raises(HTTPException) as error:
        await list_upcoming_renewals(
            tenant_id=None, days_ahead=120, badge="all", auto_renew_only=False,
            search=None, current_user=SimpleNamespace(tenant_id="test-tenant"), session=session,
        )
    assert error.value.status_code == 503
