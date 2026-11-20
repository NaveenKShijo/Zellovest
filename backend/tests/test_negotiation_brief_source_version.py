"""Source fingerprints used to validate cached negotiation briefs."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import HTTPException

from zellovest_agentic.api.routers import negotiation


@pytest.mark.asyncio
async def test_source_version_changes_with_records_and_indexed_passages(monkeypatch):
    """Changed records or retrieved passages invalidate a vendor's cached brief."""
    vendor_id = uuid4()
    user = SimpleNamespace(tenant_id="tenant-a")
    vendor = SimpleNamespace(name="Adobe")
    rows = [{"id": "document-1", "status": "staged"}]
    passages = [{"document_id": "document-1", "content": "Old clause"}]
    session = SimpleNamespace(
        scalar=AsyncMock(return_value=vendor),
        execute=AsyncMock(),
    )
    session.execute.side_effect = lambda query: SimpleNamespace(
        mappings=lambda: SimpleNamespace(all=lambda: rows)
    )
    monkeypatch.setattr(negotiation, "search_documents", lambda **kwargs: passages)

    first = await negotiation.negotiation_source_version(vendor_id, user, session)
    same = await negotiation.negotiation_source_version(vendor_id, user, session)
    assert first == same
    rows[0]["status"] = "completed"
    changed_record = await negotiation.negotiation_source_version(vendor_id, user, session)
    assert changed_record != first
    passages[0]["content"] = "Updated clause"
    changed_passage = await negotiation.negotiation_source_version(vendor_id, user, session)
    assert changed_passage != changed_record


@pytest.mark.asyncio
async def test_source_version_fails_closed_on_unavailable_sources(monkeypatch):
    """Do not declare a cached brief fresh when a source cannot be checked."""
    session = SimpleNamespace(
        scalar=AsyncMock(return_value=SimpleNamespace(name="Adobe")),
        execute=AsyncMock(side_effect=RuntimeError("database unavailable")),
    )
    with pytest.raises(HTTPException) as error:
        await negotiation.negotiation_source_version(uuid4(), SimpleNamespace(tenant_id="tenant-a"), session)
    assert error.value.status_code == 503
