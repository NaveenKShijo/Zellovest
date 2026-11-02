"""GET /documents list & detail contract tests (JWT + fake GCS + fake DB)."""

import json
import os
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://localhost/zellovest")
os.environ.setdefault("ASYNC_DATABASE_URL", "postgresql+asyncpg://localhost/zellovest")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("GCS_RAW_BUCKET", "tenant-bucket")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret")
os.environ.setdefault("FRONTEND_URL", "http://localhost:3000")

from fastapi.testclient import TestClient  # noqa: E402
from zellovest_ingestion.api.deps import (  # noqa: E402
    get_current_user,
    get_db_session,
    get_gcs_reader_dep,
    get_gcs_signer_dep,
)
from zellovest_ingestion.config import IngestionAPISettings as Settings  # noqa: E402
from zellovest_ingestion.main import create_app  # noqa: E402
from zellovest_ingestion.schemas.documents import (  # noqa: E402
    EXTRACTED_CONFIDENCE_THRESHOLD,
    derived_status,
)
from zellovest_shared.db.models import UploadStatus as DbUploadStatus  # noqa: E402
from zellovest_shared.workers.gcs_client import FakeGcsSigner  # noqa: E402


class _RowsResult:
    """Queue result exposing ``.all()`` (list/provider selects)."""

    def __init__(self, rows: list[Any]) -> None:
        """Store the row tuples to yield."""
        self._rows = rows

    def all(self) -> list[Any]:
        """Return the queued rows."""
        return self._rows


class _ScalarResult:
    """Queue result exposing ``.scalar_one()`` (count select)."""

    def __init__(self, value: Any) -> None:
        """Store the scalar value."""
        self._value = value

    def scalar_one(self) -> Any:
        """Return the queued scalar."""
        return self._value


class _OptionalResult:
    """Queue result exposing ``.scalar_one_or_none()`` (artifact select)."""

    def __init__(self, value: Any) -> None:
        """Store the optional value."""
        self._value = value

    def scalar_one_or_none(self) -> Any:
        """Return the queued optional value."""
        return self._value


class _FakeSession:
    """Stand-in AsyncSession: FIFO execute queue + fixed ``get`` row."""

    def __init__(
        self,
        upload_row: Any = None,
        execute_results: list[Any] | None = None,
    ) -> None:
        """Initialize with the row served by ``get`` and queued results.

        Args:
            upload_row: Row returned by ``session.get`` (None → 404).
            execute_results: FIFO queue of result wrappers consumed by
                ``execute`` in router call order.
        """
        self.upload_row = upload_row
        self._results = list(execute_results or [])
        self.commits = 0

    def add(self, row: Any) -> None:
        """Track added rows (unused for read-only tests)."""
        del row

    async def commit(self) -> None:
        """Count commits."""
        self.commits += 1

    async def get(self, model: Any, key: Any) -> Any:
        """Serve the preloaded lease row regardless of model/key."""
        del model, key
        return self.upload_row

    async def execute(self, stmt: Any) -> Any:
        """Pop one queued result in router call order."""
        del stmt
        assert self._results, "router issued more executes than queued results"
        return self._results.pop(0)


def _lease(**over: Any) -> SimpleNamespace:
    """Build a duck-typed uploads row for the router mappers."""
    now = datetime.now(UTC)
    status = over.pop("status", DbUploadStatus.COMPLETED)
    base: dict[str, Any] = {
        "id": uuid.uuid4(),
        "tenant_id": "default-org",
        "vendor_id": None,
        "filename": "ACME_Invoice_2026-04.pdf",
        "gcs_key": f"uploads/default-org/invoice/{uuid.uuid4().hex}/ACME_Invoice_2026-04.pdf",
        "mime_type": "application/pdf",
        "size_expected": 48213,
        "document_type": "invoice",
        "document_type_confidence": 0.93,
        "classification_method": "jev_choice",
        "status": status,
        "error": None,
        "expires_at": None,
        "created_at": now - timedelta(days=1),
        "updated_at": now,
    }
    base.update(over)
    return SimpleNamespace(**base)


def _artifact(**over: Any) -> SimpleNamespace:
    """Build a duck-typed extraction_artifacts row."""
    now = datetime.now(UTC)
    base: dict[str, Any] = {
        "id": uuid.uuid4(),
        "tenant_id": "default-org",
        "upload_id": uuid.uuid4(),
        "source_gcs_key": "uploads/default-org/invoice/x/file.pdf",
        "artifact_gcs_key": "artifacts/default-org/x/extraction.json",
        "route": "python",
        "file_type": "digital_pdf",
        "text_chars": 8123,
        "extraction_method": "pymupdf_pdfplumber",
        "extraction_confidence": Decimal("0.94"),
        "text_snippet": "INVOICE page snippet",
        "classification": {"document_type": "invoice", "confidence": 0.93},
        "created_at": now,
        "updated_at": now,
    }
    base.update(over)
    return SimpleNamespace(**base)


class _FakeReader:
    """Fake GcsObjectReader serving preloaded artifact bytes."""

    def __init__(self, blobs: dict[str, bytes]) -> None:
        """Store the blob map keyed by object key."""
        self._blobs = blobs

    def get_object_info(self, *, bucket: str, key: str) -> Any:
        """Return None (unused in these paths)."""
        del bucket, key
        return None

    def download_bytes(self, *, bucket: str, key: str) -> bytes | None:
        """Serve the blob keyed by the artifact key."""
        del bucket
        return self._blobs.get(key)

    def delete_object(self, *, bucket: str, key: str) -> bool:
        """No-op delete."""
        del bucket, key
        return False


def _make_client(
    session: _FakeSession | None = None,
    reader: _FakeReader | None = None,
    authed: bool = True,
) -> TestClient:
    """Build a TestClient with JWT/GCS/DB fakes wired in."""
    app = create_app(Settings())  # type: ignore[call-arg]
    fake_session = session or _FakeSession(upload_row=None)

    async def _fake_session_gen():  # type: ignore[no-untyped-def]
        yield fake_session

    app.dependency_overrides[get_db_session] = _fake_session_gen
    app.dependency_overrides[get_gcs_signer_dep] = lambda: FakeGcsSigner()
    app.dependency_overrides[get_gcs_reader_dep] = lambda: reader or _FakeReader({})
    if authed:
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
            id=uuid.uuid4(), email="member@example.com"
        )
    return TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# derived_status (unit)
# ---------------------------------------------------------------------------


def test_derived_status_mapping() -> None:
    """Lease status + confidence map onto the four explorer pills."""
    assert derived_status("pending", None).value == "processing"
    assert derived_status("staged", None).value == "processing"
    assert derived_status("processing", None).value == "processing"
    assert derived_status("failed", None).value == "failed"
    assert (
        derived_status("completed", 0.95).value == "extracted"
    )  # exactly at threshold boundary is trusted
    assert derived_status("completed", Decimal("0.94")).value == "extracted"
    assert derived_status("completed", 0.4).value == "review_needed"
    assert derived_status("completed", None).value == "review_needed"


def test_extraction_threshold_is_seventy_percent() -> None:
    """Guard the PRD §7 human-in-the-loop threshold constant."""
    assert EXTRACTED_CONFIDENCE_THRESHOLD == 0.70


# ---------------------------------------------------------------------------
# GET /documents (list)
# ---------------------------------------------------------------------------


def test_list_returns_enriched_rows() -> None:
    """List maps lease+artifact rows to explorer items with vendor tags."""
    lease = _lease()
    artifact = _artifact(upload_id=lease.id)
    vendor = SimpleNamespace(id=uuid.uuid4(), name="Adobe Inc.")
    session = _FakeSession(
        execute_results=[
            _RowsResult([(lease, artifact)]),
            _ScalarResult(1),
            _RowsResult([(vendor.id, vendor.name)]),
        ]
    )
    client = _make_client(session=session)
    lease.vendor_id = str(vendor.id)

    response = client.get(
        "/api/v1/documents",
        params={"document_type": "invoice", "page": 1, "page_size": 20},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["page"] == 1
    doc = body["documents"][0]
    assert doc["id"] == str(lease.id)
    assert doc["filename"] == lease.filename
    assert doc["status"] == "extracted"
    assert doc["upload_status"] == "completed"
    assert doc["vendor_name"] == "Adobe Inc."
    assert doc["has_artifact"] is True
    assert doc["extraction_confidence"] == 0.94
    assert doc["document_type"] == "invoice"


def test_list_accepts_status_filter_param() -> None:
    """status param is accepted (SQL-side filter exercised live)."""
    lease = _lease(status=DbUploadStatus.PROCESSING)
    session = _FakeSession(
        execute_results=[_RowsResult([(lease, None)]), _ScalarResult(1), _RowsResult([])]
    )
    client = _make_client(session=session)
    response = client.get("/api/v1/documents", params={"status": "processing"})
    assert response.status_code == 200
    assert response.json()["documents"][0]["status"] == "processing"


def test_list_requires_auth() -> None:
    """No JWT → 401 (no local-dev bypass)."""
    client = _make_client(authed=False)
    response = client.get("/api/v1/documents")
    assert response.status_code == 401


def test_list_accepts_multi_type_filter_param() -> None:
    """``document_types=policy,other`` (merged tab) is accepted and applied."""
    lease = _lease(document_type="policy")
    session = _FakeSession(
        execute_results=[_RowsResult([(lease, None)]), _ScalarResult(1), _RowsResult([])]
    )
    client = _make_client(session=session)
    response = client.get("/api/v1/documents", params={"document_types": "policy,other"})
    assert response.status_code == 200
    assert response.json()["documents"][0]["document_type"] == "policy"


def test_list_resolves_vendor_name_filter() -> None:
    """vendor_id=<name> matches its registry UUID and still tags canonical names."""
    lease = _lease()
    vendor_id = uuid.uuid4()
    lease.vendor_id = str(vendor_id)
    session = _FakeSession(
        execute_results=[
            _RowsResult([(vendor_id,)]),                       # name → ids lookup
            _RowsResult([(lease, None)]),                      # page select
            _ScalarResult(1),                                  # count
            _RowsResult([(vendor_id, "Adobe Inc.")]),          # id → name map
        ]
    )
    client = _make_client(session=session)
    response = client.get("/api/v1/documents", params={"vendor_id": "Adobe"})
    assert response.status_code == 200
    assert response.json()["documents"][0]["vendor_name"] == "Adobe Inc."


# ---------------------------------------------------------------------------
# GET /documents/{id} (detail)
# ---------------------------------------------------------------------------


def _artifact_payload() -> dict[str, Any]:
    """Build a realistic persisted artifact payload."""
    return {
        "schema_version": 1,
        "extraction": {
            "route": "python",
            "extraction_confidence": 0.94,
            "full_text": "INVOICE ...",
            "pages": [{"page_number": 1, "text": "INVOICE"}],
            "entities": [
                {
                    "field": "invoice_number",
                    "value": "INV-2026-045",
                    "confidence": 0.97,
                    "page": 1,
                }
            ],
            "tables": [],
        },
        "provenance": {"field": "document_type", "value": "invoice", "page": 0},
        "entity_provenance": [],
    }


def test_detail_returns_parsed_artifact() -> None:
    """Detail returns properties + classification + parsed artifact JSON."""
    lease = _lease()
    artifact = _artifact(upload_id=lease.id)
    vendor = SimpleNamespace(id=uuid.uuid4(), name="Adobe Inc.")
    lease.vendor_id = str(vendor.id)
    payload_bytes = json.dumps(_artifact_payload()).encode()
    session = _FakeSession(
        upload_row=lease,
        execute_results=[
            _OptionalResult(artifact),
            _RowsResult([(vendor.id, vendor.name)]),
        ],
    )
    reader = _FakeReader({artifact.artifact_gcs_key: payload_bytes})
    client = _make_client(session=session, reader=reader)
    response = client.get(f"/api/v1/documents/{lease.id}")
    assert response.status_code == 200
    body = response.json()
    assert body["filename"] == lease.filename
    assert body["status"] == "extracted"
    assert body["extraction_confidence"] == 0.94
    assert body["classification"]["document_type"] == "invoice"
    assert body["artifact"]["extraction"]["entities"][0]["value"] == "INV-2026-045"


def test_detail_without_artifact_omits_payload() -> None:
    """Legacy lease with no artifact row → properties only, no 500."""
    lease = _lease()
    vendor = SimpleNamespace(id=uuid.uuid4(), name="Adobe Inc.")
    lease.vendor_id = str(vendor.id)
    session = _FakeSession(
        upload_row=lease,
        execute_results=[
            _OptionalResult(None),
            _RowsResult([(vendor.id, vendor.name)]),
        ],
    )
    client = _make_client(session=session)
    response = client.get(f"/api/v1/documents/{lease.id}")
    assert response.status_code == 200
    body = response.json()
    assert body["artifact"] is None
    assert body["has_artifact"] is False


def test_detail_unknown_document_returns_404() -> None:
    """Unknown/foreign-tenant lease → 404 (tenant-scoped lookup)."""
    session = _FakeSession(upload_row=None)
    client = _make_client(session=session)
    response = client.get(f"/api/v1/documents/{uuid.uuid4()}")
    assert response.status_code == 404


def test_detail_bad_blob_still_returns_properties() -> None:
    """Artifact unreadable in GCS → 200 with artifact=None (graceful)."""
    lease = _lease()
    artifact = _artifact(upload_id=lease.id)
    vendor = SimpleNamespace(id=uuid.uuid4(), name="Adobe Inc.")
    lease.vendor_id = str(vendor.id)
    session = _FakeSession(
        upload_row=lease,
        execute_results=[
            _OptionalResult(artifact),
            _RowsResult([(vendor.id, vendor.name)]),
        ],
    )
    client = _make_client(session=session, reader=_FakeReader({}))  # blob absent
    response = client.get(f"/api/v1/documents/{lease.id}")
    assert response.status_code == 200
    assert response.json()["artifact"] is None


# ---------------------------------------------------------------------------
# GET /documents/{id}/file (signed view URL)
# ---------------------------------------------------------------------------


def test_file_returns_signed_get_url() -> None:
    """File endpoint mints a short-lived GET URL for the stored bytes."""
    lease = _lease()
    session = _FakeSession(upload_row=lease)
    client = _make_client(session=session)
    response = client.get(f"/api/v1/documents/{lease.id}/file")
    assert response.status_code == 200
    body = response.json()
    assert body["document_id"] == str(lease.id)
    assert "fake-gcs.local/tenant-bucket/" in body["url"]
    assert "get=1" in body["url"]
    datetime.fromisoformat(body["expires_at"].replace("Z", "+00:00"))


def test_file_unknown_document_returns_404() -> None:
    """File URL for unknown lease → 404."""
    session = _FakeSession(upload_row=None)
    client = _make_client(session=session)
    response = client.get(f"/api/v1/documents/{uuid.uuid4()}/file")
    assert response.status_code == 404
