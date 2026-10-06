"""Google Drive ingestion tests (RAMP-parity: OAuth + webhook + pull sync).

Covers ``/integrations/google-drive`` (connect/callback/status),
``/webhooks/google-drive``, ``/sync/google-drive``, the Drive dispatchers,
provider-bound OAuth state, and the removal of the generic ``/connectors`` APIs.
"""

import base64
import json
import os
import uuid as _uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://localhost/zellovest")
os.environ.setdefault("ASYNC_DATABASE_URL", "postgresql+asyncpg://localhost/zellovest")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("RAMP_CLIENT_ID", "test-id")
os.environ.setdefault("RAMP_CLIENT_SECRET", "test-secret")
os.environ.setdefault("RAMP_WEBHOOK_SECRET", "whsec-test")
os.environ.setdefault("CREDENTIALS_ENCRYPTION_KEY", base64.b64encode(os.urandom(32)).decode())
os.environ.setdefault("S3_RAW_BUCKET", "tenant-bucket")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret")
os.environ.setdefault("GOOGLE_DRIVE_WEBHOOK_TOKEN", "drive-chan-secret")

from zellovest_ingestion.api.deps import get_db_session  # noqa: E402
from zellovest_ingestion.config import IngestionAPISettings as Settings  # noqa: E402
from zellovest_ingestion.main import create_app  # noqa: E402


@pytest.fixture
def client():
    """Test client with fake Redis."""
    import fakeredis

    settings = Settings()  # type: ignore[call-arg]
    settings.google_drive_webhook_token = "drive-chan-secret"
    settings.google_drive_webhook_callback_url = "https://x.example/api/v1/webhooks/google-drive"
    app = create_app(settings)
    app.state.redis = fakeredis.FakeRedis(decode_responses=False)

    mock_session = AsyncMock()
    mock_session.commit = AsyncMock()

    async def fake_session():
        yield mock_session

    app.dependency_overrides[get_db_session] = fake_session
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


def _override_session(client, mock_session):
    """Point the DB dependency at a custom mock session."""

    async def fake_session():
        yield mock_session

    client.app.dependency_overrides[get_db_session] = fake_session


# --- OAuth connect -----------------------------------------------------------


def test_drive_connect_returns_google_authorization_url(client):
    """POST /connect returns a Google authorize URL with state + Drive scopes."""
    resp = client.post("/api/v1/integrations/google-drive/connect", json={"tenant_id": "t1"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "accounts.google.com" in body["authorization_url"]
    assert f"state={body['state']}" in body["authorization_url"]
    assert "drive.readonly" in body["authorization_url"]
    assert "access_type=offline" in body["authorization_url"]
    assert body["expires_in"] == 600


def test_drive_connect_defaults_to_default_org(client):
    """POST /connect defaults to default-org when body is empty."""
    resp = client.post("/api/v1/integrations/google-drive/connect", json={})
    assert resp.status_code == 200
    assert "accounts.google.com" in resp.json()["authorization_url"]


def test_oauth_state_is_provider_bound(client):
    """Ramp and Drive states are not interchangeable."""
    from zellovest_shared.security.oauth_state import consume_state, create_state

    redis_inst = client.app.state.redis
    drive_state = create_state(redis_inst, "t1", 600, provider="google_drive")
    assert consume_state(redis_inst, drive_state, expected_provider="ramp") is None

    drive_state2 = create_state(redis_inst, "t1", 600, provider="google_drive")
    assert consume_state(redis_inst, drive_state2, expected_provider="google_drive") == "t1"

    ramp_state = create_state(redis_inst, "t1", 600)
    assert consume_state(redis_inst, ramp_state) == "t1"


# --- OAuth callback / status -------------------------------------------------


def test_drive_callback_bad_state(client):
    """GET /callback returns 400 for unknown state via JSON."""
    resp = client.get("/api/v1/integrations/google-drive/callback?code=abc&state=badstate")
    assert resp.status_code == 400
    assert resp.json()["detail"] == "invalid or expired state"


def test_drive_callback_rejects_ramp_state(client):
    """A Ramp-issued state is rejected by the Drive callback (provider-bound)."""
    from zellovest_shared.security.oauth_state import create_state

    ramp_state = create_state(client.app.state.redis, "t1", 600)
    resp = client.get(
        f"/api/v1/integrations/google-drive/callback?code=abc&state={ramp_state}"
    )
    assert resp.status_code == 400


def test_drive_callback_success(client, monkeypatch):
    """GET /callback exchanges code, persists tokens, sets up watch."""
    import zellovest_ingestion.api.routers.integrations_drive as drive_module
    from zellovest_shared.schemas.integrations import TokenExchangeResult

    async def fake_exchange(*args, **kwargs):
        return TokenExchangeResult(
            access_token="ya29.valid",
            refresh_token="refresh-valid",
            expires_in=3600,
            scopes=["https://www.googleapis.com/auth/drive.readonly"],
        )

    async def fake_upsert(*args, **kwargs):
        assert kwargs.get("provider") == "google_drive"
        return MagicMock()

    def fake_watch(*args, **kwargs):
        assert kwargs.get("tenant_id") == "default-org"
        return {"channel_id": "ch-1"}

    monkeypatch.setattr(drive_module, "exchange_drive_code_for_tokens", fake_exchange)
    monkeypatch.setattr(drive_module, "aupsert_integration", fake_upsert)
    monkeypatch.setattr(drive_module, "ensure_drive_watch", fake_watch)

    from zellovest_shared.security.oauth_state import create_state

    state = create_state(client.app.state.redis, "default-org", 600, provider="google_drive")
    resp = client.get(
        f"/api/v1/integrations/google-drive/callback?code=validcode&state={state}",
        headers={"Accept": "application/json"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json() == {
        "connected": True,
        "tenant_id": "default-org",
        "provider": "google-drive",
    }


def test_drive_status_disconnected_by_default(client):
    """GET /status returns disconnected + no watch when nothing is stored."""
    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_session.execute.return_value = mock_result
    _override_session(client, mock_session)

    resp = client.get("/api/v1/integrations/google-drive/status?tenant_id=t1")
    assert resp.status_code == 200
    data = resp.json()
    assert data["connected"] is False
    assert data["provider"] == "google-drive"
    assert data["status"] == "DISCONNECTED"
    assert data["watch"] is None


def test_drive_status_connected_with_watch(client):
    """GET /status reports OAuth state plus recorded watch health."""
    mock_session = AsyncMock()
    row = MagicMock()
    row.connection_status = "ACTIVE"
    row.scopes = ["https://www.googleapis.com/auth/drive.readonly"]
    row.token_expires_at = None
    row.updated_at = None
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = row
    mock_session.execute.return_value = mock_result
    _override_session(client, mock_session)

    client.app.state.redis.set(
        "drive:channel:t1",
        json.dumps({"channel_id": "ch-1", "resource_id": "res-1", "expiration": "99"}),
    )
    resp = client.get("/api/v1/integrations/google-drive/status?tenant_id=t1")
    assert resp.status_code == 200
    data = resp.json()
    assert data["connected"] is True
    assert data["watch"]["channel_id"] == "ch-1"


# --- Pull sync ---------------------------------------------------------------


def test_sync_okta_endpoint_removed(client):
    """Okta has no pull-sync endpoint (webhook-only)."""
    resp = client.post("/api/v1/sync/okta", json={"tenant_id": "t1", "entity": "license_usage"})
    assert resp.status_code == 404


def test_sync_ramp_rejects_non_ramp_entities(client):
    """Ramp sync accepts only card_transactions/bills (Okta entities rejected)."""
    for entity in ("license_usage", "invoices", "contracts", "nope"):
        resp = client.post("/api/v1/sync/ramp", json={"tenant_id": "t1", "entity": entity})
        assert resp.status_code == 422, entity


def test_sync_ramp_accepts_ramp_entities(client, monkeypatch):
    """Ramp pull sync enqueues for card_transactions/bills."""
    import zellovest_ingestion.api.routers.sync as sync_module

    async def fake_dispatch(session, **kwargs):
        assert kwargs["source"] == "ramp"
        assert kwargs["entity"] in ("card_transactions", "bills")
        return (str(_uuid.uuid4()), "task-1", True)

    monkeypatch.setattr(sync_module, "dispatch_sync_task", fake_dispatch)
    for entity in ("card_transactions", "bills"):
        resp = client.post("/api/v1/sync/ramp", json={"tenant_id": "t1", "entity": entity})
        assert resp.status_code == 202, entity
        assert resp.json()["deduped"] is False


def test_sync_drive_enqueues_pull(client, monkeypatch):
    """POST /sync/google-drive enqueues a Drive changes.pull via checkpoint ticket."""
    import zellovest_ingestion.api.routers.sync as sync_module

    seen: dict = {}

    async def fake_dispatch(session, **kwargs):
        seen.update(kwargs)
        return (str(_uuid.uuid4()), "task-drive-1", True)

    monkeypatch.setattr(sync_module, "dispatch_drive_sync", fake_dispatch)
    resp = client.post(
        "/api/v1/sync/google-drive",
        json={"tenant_id": "t1", "cursor": "tok-1", "page_size": 50},
    )
    assert resp.status_code == 202, resp.text
    assert resp.json()["deduped"] is False
    assert seen["tenant_id"] == "t1"
    assert seen["cursor"] == "tok-1"
    assert seen["full_sync"] is False
    assert seen["page_size"] == 50


def test_sync_drive_validates_page_size(client):
    """Drive sync rejects out-of-range page sizes."""
    resp = client.post(
        "/api/v1/sync/google-drive", json={"tenant_id": "t1", "page_size": 0}
    )
    assert resp.status_code == 422


def test_dispatch_sync_task_rejects_non_ramp_source():
    """Dispatcher raises for Okta/unknown pull-sync sources (no DB touched)."""
    import asyncio

    import pytest

    from zellovest_ingestion.services.sync_dispatcher import _enqueue, dispatch_sync_task

    with pytest.raises(ValueError, match="ramp only"):
        _enqueue("okta", "license_usage", {})
    with pytest.raises(ValueError, match="ramp only"):
        _enqueue("google_drive", "documents", {})

    async def go():
        with pytest.raises(ValueError, match="ramp only"):
            await dispatch_sync_task(AsyncMock(), tenant_id="t1", source="okta", entity="x")
        with pytest.raises(ValueError, match="Unknown entity"):
            await dispatch_sync_task(
                AsyncMock(), tenant_id="t1", source="ramp", entity="license_usage"
            )

    asyncio.run(go())


def test_dispatch_drive_sync_cursor_resolution(monkeypatch):
    """Drive dispatch resumes from the latest SUCCESS cursor unless overridden."""
    import asyncio
    from types import SimpleNamespace

    import zellovest_ingestion.services.sync_dispatcher as dispatcher
    from zellovest_shared.db.models import EntityType, SyncMode

    calls: dict = {}

    async def fake_latest(session, tenant_id, entity):
        assert entity == EntityType.DOCUMENTS
        return "stored-tok"

    async def fake_create(session, **kwargs):
        calls["create"] = kwargs
        return (SimpleNamespace(sync_id=_uuid.uuid4()), True)

    def fake_enqueue(kwargs):
        calls["enqueue"] = kwargs
        return "task-9"

    monkeypatch.setattr(
        "zellovest_shared.db.repository.aget_latest_success_cursor", fake_latest
    )
    monkeypatch.setattr(dispatcher, "acreate_pending_checkpoint", fake_create)
    monkeypatch.setattr(dispatcher, "_enqueue_drive", fake_enqueue)

    async def go():
        # Default: resumes from stored cursor, incremental mode.
        sync_id, task_id, created = await dispatcher.dispatch_drive_sync(
            AsyncMock(), tenant_id="t1"
        )
        assert created is True and task_id == "task-9"
        assert calls["enqueue"]["cursor"] == "stored-tok"
        assert calls["create"]["entity"] == EntityType.DOCUMENTS
        assert calls["create"]["mode"] == SyncMode.INCREMENTAL

        # Explicit cursor wins over stored.
        await dispatcher.dispatch_drive_sync(AsyncMock(), tenant_id="t1", cursor="tok-x")
        assert calls["enqueue"]["cursor"] == "tok-x"

        # Full sync skips the stored cursor so the worker re-seeds.
        await dispatcher.dispatch_drive_sync(AsyncMock(), tenant_id="t1", full_sync=True)
        assert calls["enqueue"]["cursor"] is None
        assert calls["create"]["mode"] == SyncMode.BACKFILL
        assert sync_id is not None

    asyncio.run(go())


def test_dispatch_drive_sync_dedupes_open_checkpoint(monkeypatch):
    """Drive dispatch maps onto an open checkpoint without re-enqueueing."""
    import asyncio
    from types import SimpleNamespace

    import zellovest_ingestion.services.sync_dispatcher as dispatcher

    async def fake_create(session, **kwargs):
        return (SimpleNamespace(sync_id=_uuid.uuid4()), False)

    async def fake_latest_async(session, tenant_id, entity):
        return None

    monkeypatch.setattr(dispatcher, "acreate_pending_checkpoint", fake_create)
    monkeypatch.setattr(
        "zellovest_shared.db.repository.aget_latest_success_cursor", fake_latest_async
    )

    async def fail_enqueue(kwargs):
        raise AssertionError("must not enqueue on dedupe")

    monkeypatch.setattr(dispatcher, "_enqueue_drive", fail_enqueue)

    async def go():
        sync_id, task_id, created = await dispatcher.dispatch_drive_sync(
            AsyncMock(), tenant_id="t1", cursor="tok-1"
        )
        assert created is False
        assert task_id.startswith("existing:")
        assert sync_id is not None

    asyncio.run(go())


# --- Webhook -----------------------------------------------------------------


def test_drive_webhook_missing_channel_id(client):
    """Push without X-Goog-Channel-ID is rejected (400)."""
    resp = client.post("/api/v1/webhooks/google-drive", headers={"X-Goog-Resource-State": "add"})
    assert resp.status_code == 400


def test_drive_webhook_bad_state(client):
    """Push with unknown resource state is rejected (400)."""
    resp = client.post(
        "/api/v1/webhooks/google-drive",
        headers={"X-Goog-Channel-ID": "ch-1", "X-Goog-Resource-State": "bogus"},
    )
    assert resp.status_code == 400


def test_drive_webhook_bad_token(client):
    """Wrong channel token is rejected (401) when a token is configured."""
    resp = client.post(
        "/api/v1/webhooks/google-drive",
        headers={
            "X-Goog-Channel-ID": "ch-1",
            "X-Goog-Resource-State": "add",
            "X-Goog-Channel-Token": "wrong",
        },
    )
    assert resp.status_code == 401


def test_drive_webhook_sync_ack(client):
    """'sync' handshake is acked immediately without background work."""
    resp = client.post(
        "/api/v1/webhooks/google-drive",
        headers={
            "X-Goog-Channel-ID": "ch-1",
            "X-Goog-Resource-State": "sync",
            "X-Goog-Channel-Token": "drive-chan-secret",
        },
    )
    assert resp.status_code == 200
    assert resp.json()["resource_state"] == "sync"


def test_drive_webhook_change_enqueues_background(client, monkeypatch):
    """Change events resolve the tenant from the watch mapping and enqueue a pull."""
    import zellovest_ingestion.api.routers.webhooks as wh

    client.app.state.redis.set("drive:watch:ch-9", "t-drive")
    calls: list = []

    async def fake_process(channel_id, resource_state, tenant_id="default-org", async_database_url=None):
        calls.append((channel_id, resource_state, tenant_id))

    monkeypatch.setattr(wh, "process_google_drive_notification", fake_process)
    resp = client.post(
        "/api/v1/webhooks/google-drive",
        headers={
            "X-Goog-Channel-ID": "ch-9",
            "X-Goog-Resource-State": "update",
            "X-Goog-Channel-Token": "drive-chan-secret",
            "X-Goog-Resource-ID": "res-9",
        },
    )
    assert resp.status_code == 200
    assert resp.json() == {"received": True, "channel_id": "ch-9", "resource_state": "update"}
    assert calls == [("ch-9", "update", "t-drive")]


def test_drive_webhook_unknown_channel_falls_back_to_default_tenant(client, monkeypatch):
    """Unmapped channels fall back to the single-tenant default."""
    import zellovest_ingestion.api.routers.webhooks as wh

    calls: list = []

    async def fake_process(channel_id, resource_state, tenant_id="default-org", async_database_url=None):
        calls.append(tenant_id)

    monkeypatch.setattr(wh, "process_google_drive_notification", fake_process)
    resp = client.post(
        "/api/v1/webhooks/google-drive",
        headers={
            "X-Goog-Channel-ID": "ch-unknown",
            "X-Goog-Resource-State": "add",
            "X-Goog-Channel-Token": "drive-chan-secret",
        },
    )
    assert resp.status_code == 200
    assert calls == ["default-org"]


def test_process_notification_dispatches_pull(monkeypatch):
    """Background task opens a session and dispatches a Drive pull."""
    import asyncio

    import zellovest_ingestion.api.routers.webhooks as wh
    import zellovest_ingestion.services.sync_dispatcher as dispatcher

    mock_session = AsyncMock()
    mock_session.commit = AsyncMock()

    async def fake_scope(url):
        assert url == "db-url"
        yield mock_session

    seen: dict = {}

    async def fake_dispatch(session, **kwargs):
        seen["tenant_id"] = kwargs["tenant_id"]
        from uuid import uuid4 as _u4

        return (_u4(), "task-1", True)

    monkeypatch.setattr(wh, "async_session_scope", fake_scope)
    monkeypatch.setattr(dispatcher, "dispatch_drive_sync", fake_dispatch)

    async def go():
        await wh.process_google_drive_notification("ch-1", "add", "t1", "db-url")

    asyncio.run(go())
    assert seen == {"tenant_id": "t1"}
    mock_session.commit.assert_awaited()


def test_process_notification_without_database_skips(monkeypatch):
    """Background task without a DB URL skips the pull (unit-test path)."""
    import asyncio

    import zellovest_ingestion.api.routers.webhooks as wh
    import zellovest_ingestion.services.sync_dispatcher as dispatcher

    async def fail_dispatch(*args, **kwargs):
        raise AssertionError("must not dispatch without a database")

    monkeypatch.setattr(dispatcher, "dispatch_drive_sync", fail_dispatch)

    async def go():
        await wh.process_google_drive_notification("ch-1", "add", "t1", None)

    asyncio.run(go())


# --- Watch bookkeeping + OAuth helpers ----------------------------------------


def test_ensure_drive_watch_skipped_without_callback():
    """Watch setup is skipped when no public callback URL is configured."""
    import fakeredis

    from zellovest_ingestion.services.drive_watch import ensure_drive_watch

    redis_inst = fakeredis.FakeRedis(decode_responses=False)
    assert (
        ensure_drive_watch(
            redis_inst, tenant_id="t1", access_token="tok", webhook_callback_url=""
        )
        is None
    )


def test_ensure_drive_watch_persists_routing(monkeypatch):
    """Watch setup stores channel->tenant and tenant->watch mappings."""
    import fakeredis

    import zellovest_ingestion.services.drive_client as drive_client_module
    from zellovest_ingestion.services.drive_watch import (
        ensure_drive_watch,
        get_drive_watch,
        resolve_watch_tenant,
    )

    monkeypatch.setattr(
        drive_client_module.GoogleDriveClient,
        "get_start_page_token",
        lambda self, **k: "start-tok",
    )
    monkeypatch.setattr(
        drive_client_module.GoogleDriveClient,
        "watch_changes",
        lambda self, **k: {"id": "ch-1", "resourceId": "res-1", "expiration": "99"},
    )
    redis_inst = fakeredis.FakeRedis(decode_responses=False)
    watch = ensure_drive_watch(
        redis_inst,
        tenant_id="t1",
        access_token="tok",
        webhook_callback_url="https://x.example/api/v1/webhooks/google-drive",
        webhook_token="drive-chan-secret",
    )
    assert watch and watch["channel_id"] == "ch-1"
    assert resolve_watch_tenant(redis_inst, "ch-1") == "t1"
    assert get_drive_watch(redis_inst, "t1")["resource_id"] == "res-1"
    assert resolve_watch_tenant(redis_inst, "ch-nope") is None


def test_drive_authorize_url_offline_access():
    """Drive authorize URL requests offline access for refresh tokens."""
    from zellovest_ingestion.services.drive_oauth import build_drive_authorize_url

    url = build_drive_authorize_url(
        "https://accounts.google.com/o/oauth2/v2/auth",
        client_id="cid",
        redirect_uri="https://x.example/callback",
        state="s1",
    )
    assert "access_type=offline" in url
    assert "prompt=consent" in url
    assert "drive.readonly" in url


# --- Removed generic connector APIs ------------------------------------------


def test_connectors_routes_removed(client):
    """The generic multi-platform /connectors APIs no longer exist."""
    assert client.get("/api/v1/connectors?tenant_id=t1").status_code == 404
    assert (
        client.post("/api/v1/connectors", json={"tenant_id": "t1"}).status_code == 404
    )


def test_uploads_fallback_routes_intact(client):
    """Manual upload fallback endpoints remain registered."""
    routes = {r.path for r in client.app.routes}
    assert "/api/v1/uploads" in routes
    assert "/api/v1/uploads/{upload_id}" in routes
    resp = client.get("/api/v1/uploads?tenant_id=t1")
    assert resp.status_code == 200
    assert resp.json()["uploads"] == []
