"""POST /uploads/init contract tests (JWT + fake GCS + fake DB session)."""

import base64
import os
import uuid
from datetime import datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

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
os.environ.setdefault("GCS_RAW_BUCKET", "tenant-bucket")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret")
os.environ.setdefault("FRONTEND_URL", "http://localhost:3000")

from zellovest_ingestion.api.deps import (  # noqa: E402
    get_current_user,
    get_db_session,
    get_gcs_signer_dep,
)
from zellovest_ingestion.config import IngestionAPISettings as Settings  # noqa: E402
from zellovest_ingestion.main import create_app  # noqa: E402
from zellovest_shared.workers.gcs_client import FakeGcsSigner  # noqa: E402


class _FakeSession:
    """In-memory stand-in for an AsyncSession (captures the lease row)."""

    def __init__(self, fail_commit: bool = False) -> None:
        """Track added rows; optionally fail commits with IntegrityError."""
        self.added: list[Any] = []
        self.commits = 0
        self.rollbacks = 0
        self._fail_commit = fail_commit

    def add(self, row: Any) -> None:
        """Capture the added lease row."""
        self.added.append(row)

    async def commit(self) -> None:
        """Count commits or raise a fake unique violation."""
        self.commits += 1
        if self._fail_commit:
            raise IntegrityError("INSERT", {}, Exception("uq_uploads_gcs_key"))

    async def rollback(self) -> None:
        """Count rollbacks."""
        self.rollbacks += 1


def _make_client(
    settings: Any = None,
    session: _FakeSession | None = None,
    authed: bool = True,
) -> tuple[TestClient, _FakeSession]:
    """Build a TestClient with fake auth, GCS signer, and DB session."""
    import fakeredis

    app_settings = settings or Settings()  # type: ignore[call-arg]
    app = create_app(app_settings)
    app.state.redis = fakeredis.FakeRedis(decode_responses=False)
    fake_session = session or _FakeSession()

    async def _fake_session_gen():  # type: ignore[no-untyped-def]
        yield fake_session

    app.dependency_overrides[get_db_session] = _fake_session_gen
    app.dependency_overrides[get_gcs_signer_dep] = lambda: FakeGcsSigner()
    if authed:
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
            id=uuid.uuid4(), email="member@example.com"
        )
    client = TestClient(app, raise_server_exceptions=False)
    return client, fake_session


def test_init_happy_path_sanitizes_traversal() -> None:
    """201 returns a lease; traversal filename is sanitized into the key."""
    client, fake_session = _make_client()
    response = client.post(
        "/api/v1/uploads/init",
        json={
            "filename": "../../etc/passwd",
            "mime_type": "application/pdf",
            "size_bytes": 123,
            "document_type": "Invoice",
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["gcs_key"].startswith("uploads/default_org/invoice/")
    assert ".." not in body["gcs_key"]
    assert body["gcs_key"].endswith("/passwd")
    assert "fake-gcs.local/tenant-bucket/" in body["signed_url"]
    datetime.fromisoformat(body["expires_at"])
    uuid.UUID(body["upload_id"])

    assert len(fake_session.added) == 1
    row = fake_session.added[0]
    assert row.filename == "passwd"
    assert row.status.value == "pending"
    assert row.size_expected == 123
    assert row.vendor_id is None


def test_init_bad_mime_returns_415() -> None:
    """Disallowed MIME is rejected with 415 (router allowlist)."""
    client, _ = _make_client()
    response = client.post(
        "/api/v1/uploads/init",
        json={"filename": "a.mp4", "mime_type": "video/mp4", "size_bytes": 10},
    )
    assert response.status_code == 415


def test_init_oversize_returns_413() -> None:
    """size_bytes above GCS_MAX_UPLOAD_BYTES is rejected with 413."""
    settings = Settings()  # type: ignore[call-arg]
    small = settings.model_copy(update={"gcs_max_upload_bytes": 10})
    client, _ = _make_client(settings=small)
    response = client.post(
        "/api/v1/uploads/init",
        json={"filename": "a.pdf", "mime_type": "application/pdf", "size_bytes": 100},
    )
    assert response.status_code == 413


def test_init_missing_field_returns_422() -> None:
    """Pydantic validation failure returns 422 (no filename)."""
    client, _ = _make_client()
    response = client.post(
        "/api/v1/uploads/init",
        json={"mime_type": "application/pdf", "size_bytes": 10},
    )
    assert response.status_code == 422


def test_init_no_token_returns_401() -> None:
    """JWT auth is required even in local dev (no bypass)."""
    client, _ = _make_client(authed=False)
    response = client.post(
        "/api/v1/uploads/init",
        json={"filename": "a.pdf", "mime_type": "application/pdf", "size_bytes": 10},
    )
    assert response.status_code == 401


def test_init_empty_bucket_returns_503() -> None:
    """Missing bucket is a 503 (startup fail-fast covers real deploys)."""
    settings = Settings()  # type: ignore[call-arg]
    no_bucket = settings.model_copy(update={"gcs_raw_bucket": ""})
    client, _ = _make_client(settings=no_bucket)
    response = client.post(
        "/api/v1/uploads/init",
        json={"filename": "a.pdf", "mime_type": "application/pdf", "size_bytes": 10},
    )
    assert response.status_code == 503


def test_init_key_collision_returns_409() -> None:
    """Persistent unique violations surface as 409 after one retry."""
    client, fake_session = _make_client(session=_FakeSession(fail_commit=True))
    response = client.post(
        "/api/v1/uploads/init",
        json={"filename": "a.pdf", "mime_type": "application/pdf", "size_bytes": 10},
    )
    assert response.status_code == 409
    assert fake_session.rollbacks == 2

    _ = MagicMock()  # keep mock import used if future tests assert signer calls
