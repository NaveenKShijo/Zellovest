"""Okta batch-pull tests: client pagination, dispatcher, worker validation."""

import uuid as _uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest


def test_parse_next_after() -> None:
    """Link header `rel=next` yields the `after` cursor; else None."""
    from zellovest_shared.workers.okta_client import parse_next_after

    assert (
        parse_next_after(
            '<https://x.okta.com/api/v1/users?after=abc123&limit=200>; rel="next", '
            '<https://x.okta.com/api/v1/users?after=abc123>; rel="self"'
        )
        == "abc123"
    )
    assert parse_next_after(None) is None
    assert parse_next_after('<https://x.okta.com/api/v1/users>; rel="self"') is None


def test_okta_client_fetch_users_page(monkeypatch) -> None:
    """fetch_page sends SSWS auth + limit/after and returns (records, cursor)."""
    from zellovest_shared.workers import okta_client as client_module
    from zellovest_shared.workers.okta_client import OktaClient

    seen: dict = {}

    class FakeResp:
        status_code = 200
        headers = {
            "Link": '<https://x.okta.com/api/v1/users?after=nxt1&limit=2>; rel="next"'
        }

        def json(self):
            return [{"id": "00u1"}, {"id": "00u2"}]

    class FakeHTTP:
        def __init__(self, *args, **kwargs):
            pass

        def request(self, method, url, headers=None, params=None):
            seen.update(method=method, url=url, headers=headers, params=params)
            return FakeResp()

    monkeypatch.setattr(client_module.httpx, "Client", FakeHTTP)
    client = OktaClient("x.okta.com", "token-123")
    records, nxt = client.fetch_page("users", cursor="cur0", page_size=2)
    assert len(records) == 2
    assert nxt == "nxt1"
    assert seen["params"] == {"limit": 2, "after": "cur0"}
    assert seen["headers"]["Authorization"] == "SSWS token-123"
    assert seen["url"] == "https://x.okta.com/api/v1/users"


def test_okta_client_rejects_unknown_entity() -> None:
    """fetch_page raises PermanentOktaError for unknown collections."""
    import pytest

    from zellovest_shared.workers.okta_client import OktaClient, PermanentOktaError

    client = OktaClient.__new__(OktaClient)  # skip httpx init; validation happens first
    with pytest.raises(PermanentOktaError, match="Unknown Okta entity"):
        client.fetch_page("license_usage")


def test_okta_client_401_is_permanent(monkeypatch) -> None:
    """401 (bad token/scope) must not be retried."""
    from zellovest_shared.workers import okta_client as client_module
    from zellovest_shared.workers.okta_client import OktaClient, PermanentOktaError

    class FakeResp:
        status_code = 401
        headers = {}
        text = "Unauthorized"

        def json(self):
            raise AssertionError("must not parse body on error")

    class FakeHTTP:
        def __init__(self, *args, **kwargs):
            pass

        def request(self, *args, **kwargs):
            return FakeResp()

    monkeypatch.setattr(client_module.httpx, "Client", FakeHTTP)
    client = OktaClient("x.okta.com", "bad-token")
    with pytest.raises(PermanentOktaError, match="401"):
        client.fetch_page("users")


def test_dispatch_okta_sync_rejects_unknown_entities():
    """Dispatcher validates entity names before touching the DB."""
    import asyncio

    from zellovest_ingestion.services.sync_dispatcher import dispatch_okta_sync

    async def go():
        with pytest.raises(ValueError, match="Unknown Okta entities"):
            await dispatch_okta_sync(AsyncMock(), tenant_id="t1", entities=["nope"])

    asyncio.run(go())


def test_dispatch_okta_sync_enqueues(monkeypatch):
    """Dispatcher resolves cursor, writes checkpoint, enqueues by task name."""
    import asyncio

    from zellovest_ingestion.services import sync_dispatcher as dispatcher

    async def fake_latest(session, tenant_id=None, entity=None):
        assert tenant_id == "t1"
        return "stored-after"

    async def fake_create(session, **kwargs):
        assert kwargs["entity"].value == "events"
        assert kwargs["cursor_token"] == "stored-after"
        return (SimpleNamespace(sync_id=_uuid.uuid4()), True)

    monkeypatch.setattr(
        "zellovest_shared.db.repository.aget_latest_success_cursor", fake_latest
    )
    monkeypatch.setattr(dispatcher, "acreate_pending_checkpoint", fake_create)
    monkeypatch.setattr(dispatcher, "_enqueue_okta", lambda kwargs: "task-okta-9")

    async def go():
        sync_id, task_id, created = await dispatcher.dispatch_okta_sync(
            AsyncMock(), tenant_id="t1", entities=["logs"]
        )
        assert task_id == "task-okta-9"
        assert created is True
        assert str(sync_id)

    asyncio.run(go())


def test_sync_okta_batch_rejects_unknown_entities():
    """Worker validates entity names synchronously (no DB touched)."""
    from zellovest_workers.tasks.ingestion import sync_okta_batch

    with pytest.raises(ValueError, match="Unknown Okta entities"):
        sync_okta_batch.run("t1", entities=["nope"])


def test_sync_okta_batch_registered() -> None:
    """Task registry contains the new batch task on the ingestion queue."""
    from zellovest_workers.celery_app import celery_app

    assert "zellovest.workers.tasks.ingestion.sync_okta_batch" in set(celery_app.tasks.keys())
