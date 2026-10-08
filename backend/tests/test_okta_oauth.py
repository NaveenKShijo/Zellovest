"""Okta OAuth tests (RAMP-parity: connect/callback/status + exchange + refresh).

Covers ``/integrations/okta`` (connect/callback/status), the
``okta_oauth`` service (authorize URL, code exchange, refresh), the
provider-bound OAuth state, and the worker Bearer/SSWS scheme detection.
"""

import base64
import os
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
os.environ.setdefault("FRONTEND_URL", "http://localhost:3000")

from zellovest_ingestion.api.deps import get_db_session  # noqa: E402
from zellovest_ingestion.config import IngestionAPISettings as Settings  # noqa: E402
from zellovest_ingestion.main import create_app  # noqa: E402


@pytest.fixture
def client():
    """Test client with fake Redis and an Okta-configured deployment."""
    import fakeredis

    settings = Settings()  # type: ignore[call-arg]
    settings.okta_domain = "testorg.okta.com"
    settings.okta_client_id = "okta-test-id"
    settings.okta_client_secret = "okta-test-secret"
    settings.okta_redirect_uri = "http://localhost:8003/api/v1/integrations/okta/callback"
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


def test_okta_connect_returns_org_authorize_url(client):
    """POST /connect returns the ORG authorization-server URL with state + scopes."""
    resp = client.post("/api/v1/integrations/okta/connect", json={"tenant_id": "t1"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "testorg.okta.com/oauth2/v1/authorize" in body["authorization_url"]
    assert "/oauth2/default/" not in body["authorization_url"]
    assert f"state={body['state']}" in body["authorization_url"]
    assert "openid" in body["authorization_url"]
    assert "okta.users.read" in body["authorization_url"]
    assert "offline_access" in body["authorization_url"]
    assert body["expires_in"] == 600


def test_okta_connect_defaults_to_default_org(client):
    """POST /connect defaults to default-org when body is empty."""
    resp = client.post("/api/v1/integrations/okta/connect", json={})
    assert resp.status_code == 200
    assert "testorg.okta.com" in resp.json()["authorization_url"]


def test_okta_connect_rejects_unconfigured_deployment(client, monkeypatch):
    """POST /connect returns 400 when the Okta OAuth app is not configured."""
    monkeypatch.setattr(client.app.state.settings, "okta_domain", "")
    resp = client.post("/api/v1/integrations/okta/connect", json={"tenant_id": "t1"})
    assert resp.status_code == 400
    assert "OKTA_DOMAIN" in resp.json()["detail"]


def test_okta_connect_rejects_wrong_callback_path(client, monkeypatch):
    """POST /connect returns 400 when OKTA_REDIRECT_URI matches neither callback path."""
    monkeypatch.setattr(
        client.app.state.settings,
        "okta_redirect_uri",
        "http://localhost:8003/some/other/callback",
    )
    resp = client.post("/api/v1/integrations/okta/connect", json={"tenant_id": "t1"})
    assert resp.status_code == 400
    assert "/api/v1/integrations/okta/callback" in resp.json()["detail"]


def test_okta_connect_accepts_short_callback_path(client, monkeypatch):
    """POST /connect accepts the legacy short path (already whitelisted on tenants)."""
    monkeypatch.setattr(
        client.app.state.settings,
        "okta_redirect_uri",
        "http://localhost:8003/okta/callback",
    )
    resp = client.post("/api/v1/integrations/okta/connect", json={"tenant_id": "t1"})
    assert resp.status_code == 200, resp.text
    assert "localhost%3A8003%2Fokta%2Fcallback" in resp.json()["authorization_url"]


def test_okta_callback_alias_serves_short_path(client, monkeypatch):
    """GET /okta/callback (legacy short path) runs the same handler."""
    import zellovest_ingestion.api.routers.integrations_okta as okta_module
    from zellovest_shared.schemas.integrations import TokenExchangeResult

    async def fake_exchange(*args, **kwargs):
        return TokenExchangeResult(access_token="a", refresh_token="r", expires_in=3600, scopes=[])

    async def fake_upsert(*args, **kwargs):
        assert kwargs.get("provider") == "okta"
        return MagicMock()

    monkeypatch.setattr(okta_module, "exchange_okta_code_for_tokens", fake_exchange)
    monkeypatch.setattr(okta_module, "aupsert_integration", fake_upsert)

    from zellovest_shared.security.oauth_state import create_state

    state = create_state(client.app.state.redis, "default-org", 600, provider="okta")
    resp = client.get(
        f"/okta/callback?code=validcode&state={state}",
        headers={"Accept": "application/json"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["provider"] == "okta"


def test_okta_callback_alias_rejects_bad_state(client):
    """Unknown state on the alias path is a 400, not a 404."""
    resp = client.get("/okta/callback?code=abc&state=badstate")
    assert resp.status_code == 400


def test_okta_state_is_provider_bound(client):
    """Okta states are not interchangeable with Ramp states."""
    from zellovest_shared.security.oauth_state import consume_state, create_state

    redis_inst = client.app.state.redis
    okta_state = create_state(redis_inst, "t1", 600, provider="okta")
    assert consume_state(redis_inst, okta_state, expected_provider="ramp") is None

    okta_state2 = create_state(redis_inst, "t1", 600, provider="okta")
    assert consume_state(redis_inst, okta_state2, expected_provider="okta") == "t1"


# --- OAuth callback / status -------------------------------------------------


def test_okta_callback_bad_state(client):
    """GET /callback returns 400 for unknown state via JSON."""
    resp = client.get("/api/v1/integrations/okta/callback?code=abc&state=badstate")
    assert resp.status_code == 400
    assert resp.json()["detail"] == "invalid or expired state"


def test_okta_callback_success(client, monkeypatch):
    """GET /callback exchanges code and persists tokens on the okta row."""
    import zellovest_ingestion.api.routers.integrations_okta as okta_module
    from zellovest_shared.schemas.integrations import TokenExchangeResult

    async def fake_exchange(*args, **kwargs):
        assert kwargs["redirect_uri"].endswith("/api/v1/integrations/okta/callback")
        return TokenExchangeResult(
            access_token="okta-access",
            refresh_token="okta-refresh",
            expires_in=3600,
            scopes=["okta.users.read", "offline_access"],
        )

    async def fake_upsert(*args, **kwargs):
        assert kwargs.get("provider") == "okta"
        return MagicMock()

    monkeypatch.setattr(okta_module, "exchange_okta_code_for_tokens", fake_exchange)
    monkeypatch.setattr(okta_module, "aupsert_integration", fake_upsert)

    from zellovest_shared.security.oauth_state import create_state

    state = create_state(client.app.state.redis, "default-org", 600, provider="okta")
    resp = client.get(
        f"/api/v1/integrations/okta/callback?code=validcode&state={state}",
        headers={"Accept": "application/json"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json() == {
        "connected": True,
        "tenant_id": "default-org",
        "provider": "okta",
    }


def test_okta_status_disconnected_by_default(client):
    """GET /status returns disconnected when nothing is stored."""
    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_session.execute.return_value = mock_result
    _override_session(client, mock_session)

    resp = client.get("/api/v1/integrations/okta/status?tenant_id=t1")
    assert resp.status_code == 200
    data = resp.json()
    assert data["connected"] is False
    assert data["provider"] == "okta"


# --- Service unit tests ------------------------------------------------------


def test_build_okta_authorize_url_shape():
    """Authorize URL uses the org AS with code flow params and default scopes."""
    from zellovest_ingestion.services.okta_oauth import build_okta_authorize_url

    url = build_okta_authorize_url(
        "myorg.okta.com",
        client_id="cid",
        redirect_uri="http://localhost:8003/api/v1/integrations/okta/callback",
        state="s1",
    )
    assert url.startswith("https://myorg.okta.com/oauth2/v1/authorize?")
    assert "response_type=code" in url
    assert "client_id=cid" in url
    assert "state=s1" in url
    assert "okta.users.read" in url and "offline_access" in url


def test_okta_domain_base_normalization():
    """Bare domains, URLs and trailing slashes normalize to https://{domain}."""
    from zellovest_ingestion.services.okta_oauth import okta_domain_base

    assert okta_domain_base("myorg.okta.com") == "https://myorg.okta.com"
    assert okta_domain_base("https://myorg.okta.com/") == "https://myorg.okta.com"
    assert okta_domain_base("myorg.okta.com/") == "https://myorg.okta.com"


class _FakeTokenResponse:
    def __init__(self, status_code=200, body=None):
        self.status_code = status_code
        self._body = body or {}
        self.text = str(body)

    def json(self):
        return self._body


def _fake_async_client_factory(response, seen):
    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, url, data=None, auth=None, headers=None):
            seen.update(url=url, data=data, auth=auth)
            return response

    return FakeAsyncClient


def test_exchange_code_success(monkeypatch):
    """Code exchange uses Basic auth and parses scope string + refresh token."""
    import asyncio

    import zellovest_ingestion.services.okta_oauth as okta_module

    seen: dict = {}
    body = {
        "access_token": "at-1",
        "refresh_token": "rt-1",
        "expires_in": 3600,
        "scope": "okta.users.read offline_access",
    }
    monkeypatch.setattr(
        "httpx.AsyncClient", _fake_async_client_factory(_FakeTokenResponse(200, body), seen)
    )
    tokens = asyncio.run(
        okta_module.exchange_okta_code_for_tokens(
            "x.okta.com",
            client_id="cid",
            client_secret="csecret",
            code="code-1",
            redirect_uri="http://localhost:8003/api/v1/integrations/okta/callback",
        )
    )
    assert tokens.access_token == "at-1"
    assert tokens.refresh_token == "rt-1"
    assert tokens.scopes == ["okta.users.read", "offline_access"]
    assert seen["url"] == "https://x.okta.com/oauth2/v1/token"
    assert seen["auth"] == ("cid", "csecret")
    assert seen["data"]["grant_type"] == "authorization_code"


def test_exchange_code_rejected(monkeypatch):
    """Non-2xx token responses raise OktaOAuthExchangeError."""
    import asyncio

    import zellovest_ingestion.services.okta_oauth as okta_module
    from zellovest_ingestion.services.okta_oauth import OktaOAuthExchangeError

    monkeypatch.setattr(
        "httpx.AsyncClient",
        _fake_async_client_factory(_FakeTokenResponse(400, {"error": "invalid_grant"}), {}),
    )
    with pytest.raises(OktaOAuthExchangeError):
        asyncio.run(
            okta_module.exchange_okta_code_for_tokens(
                "x.okta.com",
                client_id="cid",
                client_secret="csecret",
                code="bad",
                redirect_uri="http://localhost/cb",
            )
        )


def test_refresh_success(monkeypatch):
    """Refresh posts grant_type=refresh_token and parses the rotated pair."""
    import asyncio

    import zellovest_ingestion.services.okta_oauth as okta_module

    seen: dict = {}
    monkeypatch.setattr(
        "httpx.AsyncClient",
        _fake_async_client_factory(
            _FakeTokenResponse(
                200, {"access_token": "at-2", "refresh_token": "rt-2", "expires_in": 3600}
            ),
            seen,
        ),
    )
    tokens = asyncio.run(
        okta_module.refresh_okta_access_token(
            "x.okta.com", client_id="cid", client_secret="csecret", refresh_token="rt-1"
        )
    )
    assert tokens.access_token == "at-2"
    assert tokens.refresh_token == "rt-2"
    assert seen["data"] == {"grant_type": "refresh_token", "refresh_token": "rt-1"}


def test_refresh_revoked_raises(monkeypatch):
    """Revoked refresh grants raise (caller must prompt Reconnect)."""
    import asyncio

    import zellovest_ingestion.services.okta_oauth as okta_module
    from zellovest_ingestion.services.okta_oauth import OktaOAuthExchangeError

    monkeypatch.setattr(
        "httpx.AsyncClient",
        _fake_async_client_factory(_FakeTokenResponse(400, {"error": "invalid_grant"}), {}),
    )
    with pytest.raises(OktaOAuthExchangeError):
        asyncio.run(
            okta_module.refresh_okta_access_token(
                "x.okta.com", client_id="cid", client_secret="csecret", refresh_token="stale"
            )
        )


# --- Worker scheme detection -------------------------------------------------


def test_bearer_client_header():
    """OktaClient supports Bearer scheme for OAuth tokens (SSWS stays default)."""
    from zellovest_shared.workers import okta_client as client_module
    from zellovest_shared.workers.okta_client import OktaClient

    assert OktaClient("x.okta.com", "t")._headers["Authorization"] == "SSWS t"
    assert (
        OktaClient("x.okta.com", "t", scheme="Bearer")._headers["Authorization"] == "Bearer t"
    )


def test_resolve_okta_auth_marks_oauth_rows_bearer():
    """Rows with offline_access scope resolve to Bearer; others stay SSWS."""
    import base64
    import os

    from zellovest_shared.security.crypto import encrypt_token
    from zellovest_workers.tasks.ingestion import _resolve_okta_auth

    key = base64.b64encode(os.urandom(32)).decode()
    access_ct, nonce = encrypt_token("oauth-at", key)

    oauth_row = MagicMock()
    oauth_row.encrypted_access_token = access_ct
    oauth_row.encrypted_refresh_token = b""
    oauth_row.encryption_nonce = nonce
    oauth_row.token_expires_at = None
    oauth_row.scopes = ["okta.users.read", "offline_access"]

    ssws_row = MagicMock()
    ssws_ct, ssws_nonce = encrypt_token("ssws-token", key)
    ssws_row.encrypted_access_token = ssws_ct
    ssws_row.encrypted_refresh_token = b""
    ssws_row.encryption_nonce = ssws_nonce
    ssws_row.token_expires_at = None
    ssws_row.scopes = []

    def fake_session_for(row):
        session = MagicMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = row
        session.execute.return_value = result
        return session

    from types import SimpleNamespace

    settings = SimpleNamespace(
        okta_domain="x.okta.com", okta_api_token="", credentials_encryption_key=key
    )
    oauth_auth = _resolve_okta_auth(fake_session_for(oauth_row), "t1", settings)
    assert (oauth_auth["scheme"], oauth_auth["token"]) == ("Bearer", "oauth-at")
    ssws_auth = _resolve_okta_auth(fake_session_for(ssws_row), "t1", settings)
    assert (ssws_auth["scheme"], ssws_auth["token"]) == ("SSWS", "ssws-token")
