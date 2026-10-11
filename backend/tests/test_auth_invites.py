"""Custom auth tests: login, invite-only onboarding, no public signup.

JWT signing (python-jose) is unavailable in the root test env by design,
so success paths patch the router's ``create_user_access_token`` with a
stub; failure paths need no JWT at all. DB access goes through
``dependency_overrides[get_db_session]`` with an in-memory fake session,
following the existing contract-test pattern.
"""

import base64
import os
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

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
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret")

import zellovest_ingestion.api.routers.auth as auth_module
from zellovest_ingestion.api.deps import get_current_user, get_db_session
from zellovest_ingestion.config import IngestionAPISettings as Settings
from zellovest_ingestion.main import create_app
from zellovest_shared.security.auth import generate_invite_token, hash_invite_token
from zellovest_shared.security.passwords import hash_password


@pytest.fixture
def client():  # type: ignore[no-untyped-def]
    """Test client for the ingestion gateway (frontend-facing auth routes)."""
    import fakeredis

    settings = Settings()  # type: ignore[call-arg]
    app = create_app(settings)
    app.state.redis = fakeredis.FakeRedis(decode_responses=False)
    return TestClient(app, raise_server_exceptions=False)


class _Scalars:
    """Minimal stand-in for a SQLAlchemy scalars result."""

    def __init__(self, value):  # type: ignore[no-untyped-def]
        self._value = value

    def first(self):  # type: ignore[no-untyped-def]
        """Return the canned row (or None)."""
        return self._value


class _ExecuteResult:
    """Minimal stand-in for a SQLAlchemy execute result."""

    def __init__(self, value):  # type: ignore[no-untyped-def]
        self._value = value

    def scalars(self):  # type: ignore[no-untyped-def]
        """Return the scalars stand-in."""
        return _Scalars(self._value)


class FakeSession:
    """In-memory async session: canned reads, recorded writes."""

    def __init__(self, execute_value=None):  # type: ignore[no-untyped-def]
        self.execute_value = execute_value
        self.added: list = []

    async def execute(self, query):  # type: ignore[no-untyped-def]
        """Return the canned row regardless of query (tests set one per case)."""
        return _ExecuteResult(self.execute_value)

    def add(self, obj):  # type: ignore[no-untyped-def]
        """Record a staged row."""
        self.added.append(obj)

    async def commit(self):  # type: ignore[no-untyped-def]
        """No-op commit."""

    async def refresh(self, obj):  # type: ignore[no-untyped-def]
        """No-op refresh."""


def _override_db(client, session):  # type: ignore[no-untyped-def]
    """Route get_db_session to the fake session; returns a cleanup callable."""

    async def fake_session():  # type: ignore[no-untyped-def]
        yield session

    client.app.dependency_overrides[get_db_session] = fake_session

    def _cleanup():  # type: ignore[no-untyped-def]
        client.app.dependency_overrides.clear()

    return _cleanup


def _override_user(client, user):  # type: ignore[no-untyped-def]
    """Route get_current_user to a fixed user (skips JWT verification)."""

    async def fake_user():  # type: ignore[no-untyped-def]
        return user

    client.app.dependency_overrides[get_current_user] = fake_user


def _member(email="ada@company.com", password="s3cret-pass"):  # type: ignore[no-untyped-def]
    """Build a fake active user row with a real password hash."""
    return SimpleNamespace(
        id=uuid.uuid4(),
        email=email,
        name="Ada Lovelace",
        password_hash=hash_password(password),
        role="procurement_member",
        tenant_id="default",
        is_active=True,
    )


def _invite(email="new@company.com", accepted=False, expired=False):  # type: ignore[no-untyped-def]
    """Build a fake invitation row."""
    now = datetime.now(UTC)
    return SimpleNamespace(
        email=email,
        token_hash="digest",
        invited_by_user_id=uuid.uuid4(),
        tenant_id="default",
        expires_at=now - timedelta(days=1) if expired else now + timedelta(days=7),
        accepted_at=now - timedelta(hours=1) if accepted else None,
    )


# --- Login -----------------------------------------------------------------


def test_login_unknown_email_returns_401(client, monkeypatch):  # type: ignore[no-untyped-def]
    """Unknown email and wrong password share one 401 message (no enumeration)."""

    async def _missing(*args, **kwargs):  # type: ignore[no-untyped-def]
        return None

    monkeypatch.setattr(auth_module, "get_user_by_email", _missing)
    cleanup = _override_db(client, FakeSession())
    try:
        response = client.post(
            "/api/v1/auth/login", json={"email": "ghost@x.co", "password": "whatever"}
        )
    finally:
        cleanup()
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid email or password."


def test_login_wrong_password_returns_401(client, monkeypatch):  # type: ignore[no-untyped-def]
    """Correct email + wrong password yields the identical 401."""
    user = _member()

    async def _find(*args, **kwargs):  # type: ignore[no-untyped-def]
        return user

    monkeypatch.setattr(auth_module, "get_user_by_email", _find)
    cleanup = _override_db(client, FakeSession())
    try:
        response = client.post(
            "/api/v1/auth/login", json={"email": user.email, "password": "wrong-pass"}
        )
    finally:
        cleanup()
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid email or password."


def test_login_success_returns_token(client, monkeypatch):  # type: ignore[no-untyped-def]
    """Valid credentials return a token envelope (JWT stubbed — no jose in test env)."""
    user = _member()

    async def _find(*args, **kwargs):  # type: ignore[no-untyped-def]
        return user

    monkeypatch.setattr(auth_module, "get_user_by_email", _find)
    monkeypatch.setattr(auth_module, "create_user_access_token", lambda *a, **k: "test-jwt")
    cleanup = _override_db(client, FakeSession())
    try:
        response = client.post(
            "/api/v1/auth/login", json={"email": user.email, "password": "s3cret-pass"}
        )
    finally:
        cleanup()
    assert response.status_code == 200
    body = response.json()
    assert body["access_token"] == "test-jwt"
    assert body["user"]["email"] == user.email


# --- Public signup is gone ---------------------------------------------------


def test_no_public_signup_route(client):  # type: ignore[no-untyped-def]
    """POST /auth/signup no longer exists (invite-only onboarding)."""
    response = client.post(
        "/api/v1/auth/signup",
        json={"email": "new@company.com", "password": "s3cret-pass", "name": "New"},
    )
    assert response.status_code == 404


# --- Invite creation ---------------------------------------------------------


def test_create_invite_requires_auth(client):  # type: ignore[no-untyped-def]
    """POST /auth/invites without a Bearer token is rejected before touching the DB."""
    response = client.post("/api/v1/auth/invites", json={"email": "new@company.com"})
    assert response.status_code == 401


def test_create_invite_returns_single_use_token(client, monkeypatch):  # type: ignore[no-untyped-def]
    """An authenticated member gets a raw token; only its hash is stored."""
    inviter = _member(email="boss@company.com")
    _override_user(client, inviter)
    session = FakeSession(execute_value=None)

    async def _find(*args, **kwargs):  # type: ignore[no-untyped-def]
        return None

    monkeypatch.setattr(auth_module, "get_user_by_email", _find)
    cleanup = _override_db(client, session)
    try:
        response = client.post(
            "/api/v1/auth/invites",
            json={"email": "new@company.com"},
            headers={"Authorization": "Bearer test-jwt"},
        )
    finally:
        cleanup()
    assert response.status_code == 201
    body = response.json()
    assert body["email"] == "new@company.com"
    assert len(session.added) == 1
    stored = session.added[0]
    assert stored.token_hash == hash_invite_token(body["invite_token"])
    assert stored.token_hash != body["invite_token"]


def test_create_invite_rejects_existing_user(client, monkeypatch):  # type: ignore[no-untyped-def]
    """Inviting an already-registered email is a 409, not a second account."""
    inviter = _member(email="boss@company.com")
    _override_user(client, inviter)

    async def _find(*args, **kwargs):  # type: ignore[no-untyped-def]
        return _member(email="new@company.com")

    monkeypatch.setattr(auth_module, "get_user_by_email", _find)
    cleanup = _override_db(client, FakeSession())
    try:
        response = client.post(
            "/api/v1/auth/invites",
            json={"email": "new@company.com"},
            headers={"Authorization": "Bearer test-jwt"},
        )
    finally:
        cleanup()
    assert response.status_code == 409


# --- Invite validation + acceptance ------------------------------------------


def test_validate_unknown_token_returns_404(client, monkeypatch):  # type: ignore[no-untyped-def]
    """Garbage tokens reveal nothing (404, same as expired/used)."""

    async def _missing(*args, **kwargs):  # type: ignore[no-untyped-def]
        return None

    monkeypatch.setattr(auth_module, "get_invite_by_token", _missing)
    cleanup = _override_db(client, FakeSession())
    try:
        response = client.get("/api/v1/auth/invites/validate?token=garbage-token-value")
    finally:
        cleanup()
    assert response.status_code == 404


def test_validate_live_invite_returns_email(client, monkeypatch):  # type: ignore[no-untyped-def]
    """A live invite discloses only the invited email + expiry."""

    async def _find(*args, **kwargs):  # type: ignore[no-untyped-def]
        return _invite()

    monkeypatch.setattr(auth_module, "get_invite_by_token", _find)
    cleanup = _override_db(client, FakeSession())
    try:
        response = client.get("/api/v1/auth/invites/validate?token=live-token-value-1234")
    finally:
        cleanup()
    assert response.status_code == 200
    assert response.json()["email"] == "new@company.com"


def test_accept_invite_creates_user_and_burns_token(client, monkeypatch):  # type: ignore[no-untyped-def]
    """Accepting creates the account, stamps accepted_at, and logs in."""
    invitation = _invite()
    newcomer = _member(email="new@company.com", password="n3w-pass-word")

    async def _find(*args, **kwargs):  # type: ignore[no-untyped-def]
        return invitation

    async def _create(*args, **kwargs):  # type: ignore[no-untyped-def]
        return newcomer

    monkeypatch.setattr(auth_module, "get_invite_by_token", _find)
    monkeypatch.setattr(auth_module, "create_user", _create)
    monkeypatch.setattr(auth_module, "create_user_access_token", lambda *a, **k: "test-jwt")
    session = FakeSession()
    cleanup = _override_db(client, session)
    try:
        response = client.post(
            "/api/v1/auth/invites/accept",
            json={
                "token": "live-token-value-1234",
                "name": "New Member",
                "password": "n3w-pass-word",
            },
        )
    finally:
        cleanup()
    assert response.status_code == 201
    assert response.json()["access_token"] == "test-jwt"
    assert invitation.accepted_at is not None


def test_accept_used_invite_returns_404(client, monkeypatch):  # type: ignore[no-untyped-def]
    """Single-use: an accepted invite cannot be claimed twice."""

    async def _find(*args, **kwargs):  # type: ignore[no-untyped-def]
        return _invite(accepted=True)

    monkeypatch.setattr(auth_module, "get_invite_by_token", _find)
    cleanup = _override_db(client, FakeSession())
    try:
        response = client.post(
            "/api/v1/auth/invites/accept",
            json={"token": "used-token-value-12345", "name": "New", "password": "n3w-pass-word"},
        )
    finally:
        cleanup()
    assert response.status_code == 404


def test_accept_expired_invite_returns_404(client, monkeypatch):  # type: ignore[no-untyped-def]
    """Expired invites are indistinguishable from invalid ones."""

    async def _find(*args, **kwargs):  # type: ignore[no-untyped-def]
        return _invite(expired=True)

    monkeypatch.setattr(auth_module, "get_invite_by_token", _find)
    cleanup = _override_db(client, FakeSession())
    try:
        response = client.post(
            "/api/v1/auth/invites/accept",
            json={"token": "old-token-value-123456", "name": "New", "password": "n3w-pass-word"},
        )
    finally:
        cleanup()
    assert response.status_code == 404


# --- Token primitives ----------------------------------------------------------


def test_invite_token_hash_roundtrip():  # type: ignore[no-untyped-def]
    """Generated tokens are URL-safe; only the SHA-256 digest is stored."""
    raw = generate_invite_token()
    assert len(raw) >= 43
    digest = hash_invite_token(raw)
    assert len(digest) == 64
    assert digest != raw
    assert hash_invite_token(raw) == digest


# --- Frictionless demo entry ---------------------------------------------------


def test_demo_login_auto_creates_account(client, monkeypatch):  # type: ignore[no-untyped-def]
    """POST /auth/demo with an empty DB creates the sandbox account (no credentials)."""
    monkeypatch.setattr(auth_module, "create_user_access_token", lambda *a, **k: "demo-jwt")
    session = FakeSession(execute_value=None)
    cleanup = _override_db(client, session)
    try:
        response = client.post("/api/v1/auth/demo")
    finally:
        cleanup()
    assert response.status_code == 200
    body = response.json()
    assert body["access_token"] == "demo-jwt"
    assert body["user"]["is_demo"] is True
    assert len(session.added) == 1
    assert session.added[0].email == "demo@zellovest.ai"
    assert session.added[0].is_demo is True


def test_demo_login_reuses_existing_account(client, monkeypatch):  # type: ignore[no-untyped-def]
    """Second demo click returns the existing row without inserting."""
    existing = _member(email="demo@zellovest.ai")
    existing.is_demo = True
    monkeypatch.setattr(auth_module, "create_user_access_token", lambda *a, **k: "demo-jwt")
    session = FakeSession(execute_value=existing)
    cleanup = _override_db(client, session)
    try:
        response = client.post("/api/v1/auth/demo")
    finally:
        cleanup()
    assert response.status_code == 200
    assert session.added == []


def test_demo_account_cannot_invite(client):  # type: ignore[no-untyped-def]
    """Sandbox explores but cannot onboard: invites are 403 for demo sessions."""
    demo_user = _member(email="demo@zellovest.ai")
    demo_user.is_demo = True
    _override_user(client, demo_user)
    session = FakeSession()
    cleanup = _override_db(client, session)
    try:
        response = client.post(
            "/api/v1/auth/invites",
            json={"email": "new@company.com"},
            headers={"Authorization": "Bearer demo-jwt"},
        )
    finally:
        cleanup()
    assert response.status_code == 403
    assert session.added == []


# --- stdlib HS256 JWT ------------------------------------------------------------


def test_jwt_matches_reference_vector():  # type: ignore[no-untyped-def]
    """Our signer reproduces the jwt.io HS256 reference signature exactly."""
    from zellovest_shared.security.jwt import _sign

    signing_input = (
        "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"
        ".eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4gRG9lIiwiaWF0IjoxNTE2MjM5MDIyfQ"
    )
    expected = "SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
    assert _sign(signing_input, "your-256-bit-secret") == expected


def test_jwt_roundtrip_and_tamper_rejection():  # type: ignore[no-untyped-def]
    """Issued tokens verify; any alteration or malformed input yields None."""
    from zellovest_shared.security.jwt import create_user_access_token, decode_token

    token = create_user_access_token("uid-1", "ada@example.com")
    payload = decode_token(token)
    assert payload is not None
    assert (payload.sub, payload.user_id, payload.email) == ("uid-1", "uid-1", "ada@example.com")
    assert decode_token(token + "tamper") is None
    assert decode_token("not.a.token") is None
    assert decode_token("") is None


def test_jwt_expired_token_rejected():  # type: ignore[no-untyped-def]
    """Tokens past exp (+30s leeway) are rejected; fresh ones accepted."""
    from datetime import timedelta

    from zellovest_shared.security.jwt import create_user_access_token, decode_token

    fresh = create_user_access_token("uid-1", "a@b.co", expires_delta=timedelta(minutes=5))
    assert decode_token(fresh) is not None
    stale = create_user_access_token("uid-1", "a@b.co", expires_delta=timedelta(seconds=-120))
    assert decode_token(stale) is None
