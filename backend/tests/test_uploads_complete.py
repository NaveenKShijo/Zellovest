"""Complete + CRUD tests for manual upload leases (fake GCS + fake DB)."""

import base64
import os
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

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
os.environ.setdefault("GCS_RAW_BUCKET", "tenant-bucket")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret")
os.environ.setdefault("FRONTEND_URL", "http://localhost:3000")

import zellovest_ingestion.api.routers.uploads as uploads_module  # noqa: E402
from zellovest_ingestion.api.deps import (  # noqa: E402
    get_current_user,
    get_db_session,
    get_gcs_reader_dep,
    get_gcs_signer_dep,
)
from zellovest_ingestion.config import IngestionAPISettings as Settings  # noqa: E402
from zellovest_ingestion.main import create_app  # noqa: E402
from zellovest_shared.db.models import (  # noqa: E402
    Upload as UploadRow,
    UploadStatus as DbUploadStatus,
)
from zellovest_shared.workers.gcs_client import (  # noqa: E402
    FakeGcsBucket,
    FakeGcsReader,
    FakeGcsSigner,
)

_BUCKET = "tenant-bucket"


class _FakeExecResult:
    """Minimal execute result: scalars().all() for rows, scalar_one for count."""

    def __init__(self, rows: list[Any]) -> None:
        """Retain the canned rows."""
        self._rows = rows

    def scalars(self) -> "_FakeExecResult":
        """Return self as the scalars facade."""
        return self

    def all(self) -> list[Any]:
        """Return all canned rows."""
        return self._rows

    def scalar_one(self) -> int:
        """Return the canned row count."""
        return len(self._rows)


class _FakeSession:
    """In-memory AsyncSession: keyed store + execute/delete support."""

    def __init__(self, seed: list[Any] | None = None) -> None:
        """Index seed rows by id for get/delete."""
        self.store: dict[str, Any] = {str(r.id): r for r in (seed or [])}
        self.added: list[Any] = []

    def add(self, row: Any) -> None:
        """Capture and index the added row."""
        self.added.append(row)
        self.store[str(row.id)] = row

    async def get(self, _model: Any, ident: Any) -> Any | None:
        """Look up a row by id."""
        return self.store.get(str(ident))

    async def delete(self, row: Any) -> None:
        """Drop a row from the store."""
        self.store.pop(str(row.id), None)

    async def execute(self, _stmt: Any) -> _FakeExecResult:
        """Return all stored rows (list) or their count."""
        return _FakeExecResult(list(self.store.values()))

    async def commit(self) -> None:
        """No-op commit (in-memory)."""

    async def rollback(self) -> None:
        """No-op rollback (in-memory)."""


def _make_row(**overrides: Any) -> UploadRow:
    """Build a pending lease row with sane defaults."""
    now = datetime.now(UTC)
    defaults: dict[str, Any] = {
        "id": uuid.uuid4(),
        "tenant_id": "default_org",
        "vendor_id": None,
        "filename": "a.pdf",
        "gcs_key": "uploads/default_org/contract/abc/a.pdf",
        "mime_type": "application/pdf",
        "size_expected": 4,
        "document_type": "contract",
        "status": DbUploadStatus.PENDING,
        "error": None,
        "expires_at": now + timedelta(seconds=900),
        "created_at": now,
        "updated_at": now,
    }
    defaults.update(overrides)
    return UploadRow(**defaults)


def _make_client(session: _FakeSession) -> TestClient:
    """Build a TestClient with fake auth, GCS, and DB session."""
    import fakeredis

    app = create_app(Settings())  # type: ignore[call-arg]
    app.state.redis = fakeredis.FakeRedis(decode_responses=False)

    async def _fake_session_gen():  # type: ignore[no-untyped-def]
        yield session

    app.dependency_overrides[get_db_session] = _fake_session_gen
    app.dependency_overrides[get_gcs_signer_dep] = lambda: FakeGcsSigner()
    app.dependency_overrides[get_gcs_reader_dep] = lambda: FakeGcsReader()
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        id=uuid.uuid4(), email="member@example.com"
    )
    return TestClient(app, raise_server_exceptions=False)


def _enqueue_ok(monkeypatch: Any) -> list[dict[str, Any]]:
    """Stub the worker fan-out; capture calls and return a task id."""
    calls: list[dict[str, Any]] = []

    def _fake(**kwargs: Any) -> str:
        calls.append(kwargs)
        return "task-1"

    monkeypatch.setattr(uploads_module, "_enqueue_stage_document", _fake)
    return calls


def test_complete_happy_path(monkeypatch: Any) -> None:
    """PUT bytes → complete flips pending→staged and enqueues the worker."""
    FakeGcsBucket.clear()
    row = _make_row()
    client = _make_client(_FakeSession(seed=[row]))
    calls = _enqueue_ok(monkeypatch)
    FakeGcsBucket.put(_BUCKET, row.gcs_key, b"data", "application/pdf")

    response = client.post(f"/api/v1/uploads/{row.id}/complete")

    assert response.status_code == 200
    body = response.json()
    assert body["upload_id"] == str(row.id)
    assert body["gcs_key"] == row.gcs_key
    assert body["status"] == "staged"
    assert body["size_actual"] == 4
    assert body["task_id"] == "task-1"
    assert row.status == DbUploadStatus.STAGED
    assert calls and calls[0]["gcs_key"] == row.gcs_key
    assert calls[0]["tenant_id"] == "default_org"
    FakeGcsBucket.clear()


def test_complete_unknown_returns_404(monkeypatch: Any) -> None:
    """Unknown lease id returns 404."""
    FakeGcsBucket.clear()
    client = _make_client(_FakeSession())
    _enqueue_ok(monkeypatch)
    response = client.post(f"/api/v1/uploads/{uuid.uuid4()}/complete")
    assert response.status_code == 404
    FakeGcsBucket.clear()


def test_complete_expired_returns_410(monkeypatch: Any) -> None:
    """Expired lease is marked failed and returns 410."""
    FakeGcsBucket.clear()
    row = _make_row(expires_at=datetime.now(UTC) - timedelta(seconds=10))
    client = _make_client(_FakeSession(seed=[row]))
    _enqueue_ok(monkeypatch)
    response = client.post(f"/api/v1/uploads/{row.id}/complete")
    assert response.status_code == 410
    assert row.status == DbUploadStatus.FAILED
    FakeGcsBucket.clear()


def test_complete_missing_bytes_returns_422(monkeypatch: Any) -> None:
    """No PUT yet returns 422 (bytes absent)."""
    FakeGcsBucket.clear()
    row = _make_row()
    client = _make_client(_FakeSession(seed=[row]))
    _enqueue_ok(monkeypatch)
    response = client.post(f"/api/v1/uploads/{row.id}/complete")
    assert response.status_code == 422
    assert row.status == DbUploadStatus.PENDING
    FakeGcsBucket.clear()


def test_complete_size_mismatch_returns_422(monkeypatch: Any) -> None:
    """Wrong byte count returns 422 and keeps the lease pending."""
    FakeGcsBucket.clear()
    row = _make_row()
    client = _make_client(_FakeSession(seed=[row]))
    _enqueue_ok(monkeypatch)
    FakeGcsBucket.put(_BUCKET, row.gcs_key, b"toolongbytes", "application/pdf")
    response = client.post(f"/api/v1/uploads/{row.id}/complete")
    assert response.status_code == 422
    assert row.status == DbUploadStatus.PENDING
    FakeGcsBucket.clear()


def test_complete_idempotent_when_staged(monkeypatch: Any) -> None:
    """Repeat complete on a staged lease returns state without re-enqueue."""
    FakeGcsBucket.clear()
    row = _make_row(status=DbUploadStatus.STAGED)
    client = _make_client(_FakeSession(seed=[row]))
    calls = _enqueue_ok(monkeypatch)
    response = client.post(f"/api/v1/uploads/{row.id}/complete")
    assert response.status_code == 200
    assert response.json()["task_id"] is None
    assert calls == []
    FakeGcsBucket.clear()


def test_complete_conflict_when_processing(monkeypatch: Any) -> None:
    """Leases beyond staged are rejected with 409."""
    FakeGcsBucket.clear()
    row = _make_row(status=DbUploadStatus.PROCESSING)
    client = _make_client(_FakeSession(seed=[row]))
    _enqueue_ok(monkeypatch)
    response = client.post(f"/api/v1/uploads/{row.id}/complete")
    assert response.status_code == 409
    FakeGcsBucket.clear()


def test_list_and_get() -> None:
    """List returns seeded leases; get fetches one; unknown is 404."""
    FakeGcsBucket.clear()
    rows = [_make_row(), _make_row()]
    client = _make_client(_FakeSession(seed=rows))
    response = client.get("/api/v1/uploads")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert len(body["uploads"]) == 2
    assert body["uploads"][0]["gcs_key"]

    response = client.get(f"/api/v1/uploads/{rows[0].id}")
    assert response.status_code == 200
    assert response.json()["id"] == str(rows[0].id)

    response = client.get(f"/api/v1/uploads/{uuid.uuid4()}")
    assert response.status_code == 404
    FakeGcsBucket.clear()


def test_delete_pending_cancels_and_cleans_blob() -> None:
    """Cancelling a pending lease drops the row and its blob (204)."""
    FakeGcsBucket.clear()
    row = _make_row()
    session = _FakeSession(seed=[row])
    client = _make_client(session)
    FakeGcsBucket.put(_BUCKET, row.gcs_key, b"data", "application/pdf")
    response = client.delete(f"/api/v1/uploads/{row.id}")
    assert response.status_code == 204
    assert str(row.id) not in session.store
    assert FakeGcsBucket._blobs.get((_BUCKET, row.gcs_key)) is None
    FakeGcsBucket.clear()


def test_delete_non_pending_returns_409() -> None:
    """Staged leases cannot be cancelled (worker may own them)."""
    FakeGcsBucket.clear()
    row = _make_row(status=DbUploadStatus.STAGED)
    client = _make_client(_FakeSession(seed=[row]))
    response = client.delete(f"/api/v1/uploads/{row.id}")
    assert response.status_code == 409
    FakeGcsBucket.clear()
