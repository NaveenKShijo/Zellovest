"""Ingestion API contract tests (mocked DB/Redis/Celery)."""

import base64
import hashlib
import hmac
import json
import os
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

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
os.environ.setdefault("S3_RAW_BUCKET", "tenant-bucket")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret")
os.environ.setdefault("FRONTEND_URL", "http://localhost:3000")

from zellovest_ingestion.config import IngestionAPISettings as Settings
from zellovest_ingestion.main import create_app
from zellovest_shared.schemas.integrations import TokenExchangeResult
from zellovest_shared.security.oauth_state import create_state


@pytest.fixture
def client():  # type: ignore[no-untyped-def]
    """Test client with fake Redis (state store)."""
    import fakeredis

    settings = Settings()  # type: ignore[call-arg]
    app = create_app(settings)
    app.state.redis = fakeredis.FakeRedis(decode_responses=False)
    return TestClient(app, raise_server_exceptions=False)


def test_connect_returns_authorization_url(client):  # type: ignore[no-untyped-def]
    """POST /connect returns an authorization URL embedding a state token and scopes."""
    response = client.post("/api/v1/integrations/ramp/connect", json={"tenant_id": "t1"})
    assert response.status_code == 200
    body = response.json()
    assert "app.ramp.com" in body["authorization_url"]
    assert f"state={body['state']}" in body["authorization_url"]
    assert "transactions%3Aread" in body["authorization_url"]
    assert "bills%3Aread" in body["authorization_url"]
    assert body["expires_in"] == 600


def test_connect_defaults_to_default_org(client):  # type: ignore[no-untyped-def]
    """POST /connect defaults to default-org and default scopes when body is empty."""
    response = client.post("/api/v1/integrations/ramp/connect", json={})
    assert response.status_code == 200
    body = response.json()
    assert "app.ramp.com" in body["authorization_url"]
    assert "state=" in body["authorization_url"]
    assert "bills%3Aread" in body["authorization_url"]


def test_callback_bad_state(client):  # type: ignore[no-untyped-def]
    """GET /callback returns 400 for unknown state via JSON."""
    response = client.get("/api/v1/integrations/ramp/callback?code=abc&state=badstate")
    assert response.status_code == 400
    assert response.json()["detail"] == "invalid or expired state"


def test_callback_bad_state_browser_redirect(client):  # type: ignore[no-untyped-def]
    """GET /callback with Accept: text/html redirects to frontend error page."""
    response = client.get(
        "/api/v1/integrations/ramp/callback?code=abc&state=badstate",
        headers={"Accept": "text/html,application/xhtml+xml"},
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert "localhost:3000/integrations" in response.headers["location"]
    assert "invalid_or_expired_state" in response.headers["location"]


def test_callback_success(client, monkeypatch):  # type: ignore[no-untyped-def]
    """GET /callback exchanges code, persists tokens, and returns success."""
    import zellovest_ingestion.api.routers.integrations as integrations_module
    from zellovest_ingestion.api.deps import get_db_session

    redis_inst = client.app.state.redis
    state = create_state(redis_inst, "default-org", 600)

    async def fake_exchange(*args, **kwargs):  # type: ignore[no-untyped-def]
        return TokenExchangeResult(
            access_token="ramp_tok_valid",
            refresh_token="ramp_ref_valid",
            expires_in=3600,
            scopes=["transactions:read", "bills:read"],
        )

    async def fake_upsert(*args, **kwargs):  # type: ignore[no-untyped-def]
        return MagicMock()

    monkeypatch.setattr(integrations_module, "exchange_code_for_tokens", fake_exchange)
    monkeypatch.setattr(integrations_module, "aupsert_integration", fake_upsert)

    mock_session = AsyncMock()
    mock_session.commit = AsyncMock()

    async def fake_session():  # type: ignore[no-untyped-def]
        yield mock_session

    client.app.dependency_overrides[get_db_session] = fake_session
    try:
        response = client.get(
            f"/api/v1/integrations/ramp/callback?code=validcode&state={state}",
            headers={"Accept": "application/json"},
        )
        assert response.status_code == 200
        assert response.json() == {
            "connected": True,
            "tenant_id": "default-org",
            "provider": "ramp",
        }
    finally:
        client.app.dependency_overrides.clear()


def test_callback_browser_redirect_on_success(client, monkeypatch):  # type: ignore[no-untyped-def]
    """GET /callback with Accept: text/html redirects to frontend with connected status."""
    import zellovest_ingestion.api.routers.integrations as integrations_module
    from zellovest_ingestion.api.deps import get_db_session

    redis_inst = client.app.state.redis
    state = create_state(redis_inst, "default-org", 600)

    async def fake_exchange(*args, **kwargs):  # type: ignore[no-untyped-def]
        return TokenExchangeResult(
            access_token="ramp_tok_valid",
            refresh_token="ramp_ref_valid",
            expires_in=3600,
            scopes=["transactions:read", "bills:read"],
        )

    async def fake_upsert(*args, **kwargs):  # type: ignore[no-untyped-def]
        return MagicMock()

    monkeypatch.setattr(integrations_module, "exchange_code_for_tokens", fake_exchange)
    monkeypatch.setattr(integrations_module, "aupsert_integration", fake_upsert)

    mock_session = AsyncMock()
    mock_session.commit = AsyncMock()

    async def fake_session():  # type: ignore[no-untyped-def]
        yield mock_session

    client.app.dependency_overrides[get_db_session] = fake_session
    try:
        response = client.get(
            f"/api/v1/integrations/ramp/callback?code=validcode&state={state}",
            headers={"Accept": "text/html,application/xhtml+xml"},
            follow_redirects=False,
        )
        assert response.status_code == 302
        assert "localhost:3000/integrations" in response.headers["location"]
        assert "status=connected" in response.headers["location"]
    finally:
        client.app.dependency_overrides.clear()


def test_status_disconnected_by_default(client):  # type: ignore[no-untyped-def]
    """GET /status returns disconnected if no record found in DB."""
    from zellovest_ingestion.api.deps import get_db_session

    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_session.execute.return_value = mock_result

    async def fake_session():  # type: ignore[no-untyped-def]
        yield mock_session

    client.app.dependency_overrides[get_db_session] = fake_session
    try:
        response = client.get("/api/v1/integrations/ramp/status?tenant_id=default-org")
        assert response.status_code == 200
        data = response.json()
        assert data["connected"] is False
        assert data["status"] == "DISCONNECTED"
    finally:
        client.app.dependency_overrides.clear()


def test_sync_validates_entity(client):  # type: ignore[no-untyped-def]
    """POST /sync rejects unknown entities with 422 (Pydantic validation)."""
    response = client.post("/api/v1/sync/ramp", json={"tenant_id": "t1", "entity": "nope"})
    assert response.status_code == 422


def test_webhook_rejects_bad_signature(client):  # type: ignore[no-untyped-def]
    """POST /webhooks/ramp returns 401 on HMAC mismatch."""
    response = client.post(
        "/api/v1/webhooks/ramp",
        content=b'{"event_id":"evt_1"}',
        headers={"X-Ramp-Signature": "deadbeef"},
    )
    assert response.status_code == 401


def test_webhook_accepts_valid_signature_with_mocks(client, monkeypatch):  # type: ignore[no-untyped-def]
    """Valid HMAC + mocked dispatch returns 200 with sync ticket."""
    import zellovest_ingestion.api.routers.webhooks as webhooks_module

    payload = {"event_id": "evt_9", "type": "transaction.created", "data": {"id": "obj_1"}}
    raw = json.dumps(payload).encode()
    sig = hmac.new(b"whsec-test", raw, hashlib.sha256).hexdigest()

    async def fake_dispatch(*args, **kwargs):  # type: ignore[no-untyped-def]
        import uuid as _uuid

        return (_uuid.uuid4(), "task-123", True)

    monkeypatch.setattr(webhooks_module, "dispatch_ramp_webhook", fake_dispatch)

    # Bypass DB dependency: override get_db_session with a dummy.
    from zellovest_ingestion.api.deps import get_db_session

    async def fake_session():  # type: ignore[no-untyped-def]
        yield AsyncMock()

    client.app.dependency_overrides[get_db_session] = fake_session
    try:
        response = client.post(
            "/api/v1/webhooks/ramp", content=raw, headers={"X-Ramp-Signature": sig}
        )
    finally:
        client.app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.json()["received"] is True


def test_healthz(client):  # type: ignore[no-untyped-def]
    """Liveness probe returns ok without dependencies."""
    assert client.get("/healthz").json() == {"status": "ok", "service": "ingestion-api"}


def test_celery_task_names_and_queues() -> None:
    """Task registry uses the agreed names and queue routing."""
    from zellovest_workers.tasks import ingestion as _tasks  # noqa: F401
    from zellovest_workers.celery_app import (
        QUEUE_ANALYTICS,
        QUEUE_DOCUMENTS,
        QUEUE_INGESTION,
        celery_app,
    )

    assert QUEUE_INGESTION == "ingestion_tasks"
    names = set(celery_app.tasks.keys())
    assert "zellovest.workers.tasks.ingestion.sync_ramp_card_transactions" in names
    assert "zellovest.workers.tasks.ingestion.sync_ramp_bills" in names
    assert "zellovest.workers.tasks.ingestion.handle_ramp_webhook_event" in names
    routes = celery_app.conf.task_routes
    assert routes["zellovest.workers.tasks.ingestion.*"]["queue"] == "ingestion_tasks"
    assert routes["zellovest.workers.tasks.document_ocr.*"]["queue"] == QUEUE_DOCUMENTS
    assert routes["zellovest.workers.tasks.ap_audit.*"]["queue"] == QUEUE_ANALYTICS
    assert celery_app.conf.task_serializer == "json"

    _ = MagicMock()  # keep mock import used for future task-delay assertions
