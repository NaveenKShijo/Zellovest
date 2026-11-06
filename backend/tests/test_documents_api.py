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

    def scalars(self) -> "_RowsResult":
        """Return self so ``execute(...).scalars().all()`` works."""
        return self


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
        scalar_results: list[Any] | None = None,
    ) -> None:
        """Initialize with the row served by ``get`` and queued results.

        Args:
            upload_row: Row returned by ``session.get`` (None → 404).
            execute_results: FIFO queue of result wrappers consumed by
                ``execute`` in router call order.
            scalar_results: FIFO queue of values returned by ``scalar``.
        """
        self.upload_row = upload_row
        self._results = list(execute_results or [])
        self._scalars = list(scalar_results or [])
        self.added: list[Any] = []
        self.deleted: list[Any] = []
        self.commits = 0
        self.flushes = 0
        self.rollbacks = 0

    def add(self, row: Any) -> None:
        """Track added rows."""
        self.added.append(row)

    async def delete(self, row: Any) -> None:
        """Track deleted rows."""
        self.deleted.append(row)

    async def commit(self) -> None:
        """Count commits."""
        self.commits += 1

    async def rollback(self) -> None:
        """Count rollbacks."""
        self.rollbacks += 1

    async def flush(self) -> None:
        """Count flushes."""
        self.flushes += 1

    async def get(self, model: Any, key: Any) -> Any:
        """Serve the preloaded lease row regardless of model/key."""
        del model, key
        return self.upload_row

    async def execute(self, stmt: Any) -> Any:
        """Pop one queued result in router call order."""
        del stmt
        assert self._results, "router issued more executes than queued results"
        return self._results.pop(0)

    async def scalar(self, stmt: Any) -> Any:
        """Pop one queued scalar in router call order."""
        del stmt
        assert self._scalars, "router issued more scalars than queued results"
        return self._scalars.pop(0)

    async def scalars(self, stmt: Any) -> Any:
        """Pop one queued result for ``session.scalars`` calls."""
        del stmt
        assert self._results, "router issued more scalars than queued results"
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
        "review_status": None,
        "review_data": None,
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
        derived_status("completed", 0.80).value == "extracted"
    )  # exactly at threshold boundary is trusted
    assert derived_status("completed", Decimal("0.94")).value == "extracted"
    assert derived_status("completed", 0.4).value == "review_needed"
    assert derived_status("completed", None).value == "review_needed"
    assert derived_status("completed", 0.4, "committed").value == "extracted"
    assert derived_status("completed", 0.94, "pending").value == "review_needed"


def test_extraction_threshold_is_eighty_percent() -> None:
    """Guard the PRD §7 human-in-the-loop threshold constant."""
    assert EXTRACTED_CONFIDENCE_THRESHOLD == 0.80


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
        scalar_results=[None],  # no promoted structured document yet
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
        scalar_results=[None],
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
        scalar_results=[None],
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


# ---------------------------------------------------------------------------
# POST /documents/{id}/review/commit (HITL → ledger)
# ---------------------------------------------------------------------------


def _review_document(document_type: str = "contract") -> SimpleNamespace:
    """Build a duck-typed structured ``documents`` row for review commits."""
    return SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id="default-org",
        upload_id=uuid.uuid4(),
        document_type=SimpleNamespace(value=document_type),
        vendor_id=None,
        status="review_needed",
    )


def _review_payload() -> dict[str, Any]:
    """Build a valid reviewer-corrected contract payload."""
    return {
        "contract_number": "MSA-2026-014",
        "vendor_name": "Adobe Inc.",
        "title": "Enterprise agreement",
        "start_date": "2026-01-01",
        "end_date": "2026-12-31",
        "renewal_date": "2026-11-01",
        "notice_period_days": 30,
        "auto_renew": True,
        "termination_clause": "Either party may terminate with 30 days notice.",
        "terms": [
            {
                "product_code": "CC-ALL",
                "description": "Creative Cloud all apps",
                "unit_price": "120.00",
                "currency": "usd",
                "uom": "seat",
                "qty_min": 10,
                "qty_max": 50,
                "discount_pct": 5,
                "effective_from": "2026-01-01",
                "effective_to": "2026-12-31",
                "escalation_pct": 3,
                "payment_terms": "Net 30",
                "freight_terms": "N/A",
                "tax_rule": "Exclusive of tax",
            }
        ],
    }


def test_review_commit_persists_verified_terms() -> None:
    """A pending review commits a contract version + human provenance."""
    lease = _lease(document_type="contract")
    artifact = _artifact(
        upload_id=lease.id,
        review_status="pending",
        review_data={"status": "pending", "field_confidence": {"unit_price": 0.55}},
    )
    document = _review_document()
    document.upload_id = lease.id
    vendor = SimpleNamespace(id=uuid.uuid4(), name="Adobe Inc.")
    session = _FakeSession(
        upload_row=lease,
        execute_results=[
            _OptionalResult(artifact),          # artifact with FOR UPDATE
            _OptionalResult(document),          # structured document
            _OptionalResult(vendor),            # vendor lookup
            _RowsResult([]),                    # no matching tenant contracts
        ],
        scalar_results=[None],                  # max version → first version
    )
    client = _make_client(session=session)

    response = client.post(f"/api/v1/documents/{lease.id}/review/commit", json=_review_payload())

    assert response.status_code == 200
    body = response.json()
    assert body["document_id"] == str(lease.id)
    assert body["review_status"] == "committed"
    assert len(body["term_version_ids"]) == 1
    assert session.commits == 1
    assert artifact.review_status == "committed"
    assert artifact.review_data["status"] == "committed"
    assert artifact.review_data["reviewer_email"] == "member@example.com"
    assert document.status == "extracted"
    # Contract + version + line + term + nine header provenance + ten term
    # provenance rows.
    assert len(session.added) == 1 + 1 + 1 + 1 + 9 + 10


def test_review_commit_rejects_missing_pending_review() -> None:
    """Only a pending human review can be committed."""
    lease = _lease(document_type="contract")
    artifact = _artifact(upload_id=lease.id, review_status=None)
    session = _FakeSession(
        upload_row=lease,
        execute_results=[_OptionalResult(artifact)],
    )
    client = _make_client(session=session)

    response = client.post(f"/api/v1/documents/{lease.id}/review/commit", json=_review_payload())

    assert response.status_code == 409
    assert session.commits == 0


def test_review_commit_rejects_non_contract_documents() -> None:
    """Commercial-term review applies to contracts and amendments only."""
    lease = _lease(document_type="invoice")
    artifact = _artifact(upload_id=lease.id, review_status="pending")
    document = _review_document("invoice")
    document.upload_id = lease.id
    session = _FakeSession(
        upload_row=lease,
        execute_results=[_OptionalResult(artifact), _OptionalResult(document)],
    )
    client = _make_client(session=session)

    response = client.post(f"/api/v1/documents/{lease.id}/review/commit", json=_review_payload())

    assert response.status_code == 422
    assert session.commits == 0


def test_review_commit_rejects_conflicting_contract_number() -> None:
    """A different document cannot overwrite an existing contract number."""
    lease = _lease(document_type="contract")
    artifact = _artifact(upload_id=lease.id, review_status="pending")
    document = _review_document()
    document.upload_id = lease.id
    vendor = SimpleNamespace(id=uuid.uuid4(), name="Adobe Inc.")
    existing = SimpleNamespace(
        id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        contract_number="MSA-2026-014",
    )
    session = _FakeSession(
        upload_row=lease,
        execute_results=[
            _OptionalResult(artifact),
            _OptionalResult(document),
            _OptionalResult(vendor),
            _RowsResult([existing]),
        ],
    )
    client = _make_client(session=session)

    response = client.post(f"/api/v1/documents/{lease.id}/review/commit", json=_review_payload())

    assert response.status_code == 409
    assert session.commits == 0


def test_detail_returns_pending_review_state() -> None:
    """Detail exposes the review record so the drawer can render it."""
    lease = _lease(document_type="contract")
    review = {
        "status": "pending",
        "confidence_threshold": 0.8,
        "field_confidence": {"unit_price": 0.55, "title": 0.92},
        "data": {"contract_number": "MSA-2026-014"},
        "reason": "unit price (55%) below threshold",
    }
    artifact = _artifact(
        upload_id=lease.id,
        review_status="pending",
        review_data=review,
        extraction_confidence=Decimal("0.62"),
    )
    session = _FakeSession(
        upload_row=lease,
        execute_results=[_OptionalResult(artifact), _RowsResult([])],
        scalar_results=[None],  # contract document exists, but no ledger header
    )
    client = _make_client(session=session)

    response = client.get(f"/api/v1/documents/{lease.id}")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "review_needed"
    assert body["review"]["status"] == "pending"
    assert body["review"]["field_confidence"]["unit_price"] == 0.55


# ---------------------------------------------------------------------------
# POST /documents/{id}/review/commit-invoice (invoice HITL → ledger)
# ---------------------------------------------------------------------------


def _invoice_review_document() -> SimpleNamespace:
    """Build a duck-typed structured invoice document row."""
    return SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id="default-org",
        upload_id=uuid.uuid4(),
        document_type=SimpleNamespace(value="invoice"),
        vendor_id=None,
        status="review_needed",
    )


def _invoice_review_payload() -> dict[str, Any]:
    """Build a valid reviewer-corrected invoice payload."""
    return {
        "invoice_number": "1038",
        "vendor_name": "Acme Design",
        "invoice_date": "2026-11-03",
        "due_date": "2026-12-03",
        "currency": "usd",
        "subtotal": "75.00",
        "tax_amount": "6.00",
        "total_amount": "81.00",
        "reviewer_notes": "Verified against the source PDF.",
        "line_items": [
            {
                "description": "Design AI Model",
                "product_code": None,
                "quantity": "1",
                "unit_price": "75.00",
            }
        ],
    }


def test_invoice_review_commit_updates_existing_invoice() -> None:
    """A low-confidence invoice review updates its header and line items."""
    lease = _lease(document_type="invoice")
    artifact = _artifact(
        upload_id=lease.id,
        review_status=None,
        extraction_confidence=Decimal("0.5000"),
    )
    document = _invoice_review_document()
    vendor = SimpleNamespace(id=uuid.uuid4(), name="Acme Design")
    invoice = SimpleNamespace(
        id=uuid.uuid4(),
        invoice_number="OLD-1038",
        invoice_date=datetime(2026, 1, 1, tzinfo=UTC),
        due_date=None,
        currency="USD",
        subtotal=0.0,
        tax_amount=0.0,
        total_amount=0.0,
        vendor_id=None,
        extra=None,
    )
    line = SimpleNamespace(
        id=uuid.uuid4(),
        line_no=1,
        description="old line",
        product_code=None,
        quantity=1.0,
        unit_price=1.0,
        total=1.0,
    )
    extra_line = SimpleNamespace(
        id=uuid.uuid4(),
        line_no=2,
        description="removed line",
        product_code=None,
        quantity=1.0,
        unit_price=1.0,
        total=1.0,
    )
    session = _FakeSession(
        upload_row=lease,
        execute_results=[
            _OptionalResult(artifact),          # artifact with FOR UPDATE
            _OptionalResult(document),          # structured document
            _OptionalResult(vendor),            # vendor lookup
            _OptionalResult(invoice),           # existing invoice
            _OptionalResult(None),              # no conflicting invoice
            _RowsResult([line, extra_line]),    # existing invoice lines
        ],
    )
    client = _make_client(session=session)

    response = client.post(
        f"/api/v1/documents/{lease.id}/review/commit-invoice",
        json=_invoice_review_payload(),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["invoice_id"] == str(invoice.id)
    assert body["review_status"] == "committed"
    assert session.commits == 1
    assert artifact.review_status == "committed"
    assert artifact.review_data["status"] == "committed"
    assert artifact.review_data["reviewer_email"] == "member@example.com"
    assert artifact.review_data["reviewer_notes"] == "Verified against the source PDF."
    assert document.status == "extracted"
    assert invoice.invoice_number == "1038"
    assert invoice.subtotal == 75.0
    assert invoice.tax_amount == 6.0
    assert line.description == "Design AI Model"
    assert line.unit_price == 75.0
    assert line.total == 75.0
    assert extra_line in session.deleted
    # 8 header fields + 5 line fields on unchanged/new rows.
    assert len(session.added) == 8 + 5


def test_invoice_review_commit_creates_missing_invoice() -> None:
    """A failed provisional upsert is repaired by the reviewer commit."""
    lease = _lease(document_type="invoice")
    artifact = _artifact(
        upload_id=lease.id,
        review_status=None,
        extraction_confidence=Decimal("0.5000"),
    )
    document = _invoice_review_document()
    vendor = SimpleNamespace(id=uuid.uuid4(), name="Acme Design")
    session = _FakeSession(
        upload_row=lease,
        execute_results=[
            _OptionalResult(artifact),
            _OptionalResult(document),
            _OptionalResult(vendor),
            _OptionalResult(None),      # no existing invoice
            _OptionalResult(None),      # no conflicting invoice
            _RowsResult([]),            # no existing lines
        ],
    )
    client = _make_client(session=session)

    response = client.post(
        f"/api/v1/documents/{lease.id}/review/commit-invoice",
        json=_invoice_review_payload(),
    )

    assert response.status_code == 200
    assert session.commits == 1
    assert artifact.review_status == "committed"
    # New invoice + new line + 8 header provenance + 5 line provenance.
    assert len(session.added) == 1 + 1 + 8 + 5


def test_invoice_review_commit_adopts_reuploaded_invoice() -> None:
    """A duplicate upload clears review against the existing ledger invoice."""
    lease = _lease(document_type="invoice")
    artifact = _artifact(
        upload_id=lease.id,
        review_status=None,
        extraction_confidence=Decimal("0.5000"),
    )
    document = _invoice_review_document()
    vendor = SimpleNamespace(id=uuid.uuid4(), name="Acme Design")
    conflicting_invoice = SimpleNamespace(
        id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        invoice_number="1038",
        invoice_date=datetime(2026, 1, 1, tzinfo=UTC),
        due_date=None,
        currency="USD",
        subtotal=1.0,
        tax_amount=0.0,
        total_amount=1.0,
        vendor_id=None,
        extra=None,
    )
    line = SimpleNamespace(
        id=uuid.uuid4(),
        line_no=1,
        description="old line",
        product_code=None,
        quantity=1.0,
        unit_price=1.0,
        total=1.0,
    )
    session = _FakeSession(
        upload_row=lease,
        execute_results=[
            _OptionalResult(artifact),
            _OptionalResult(document),
            _OptionalResult(vendor),
            _OptionalResult(None),                  # no invoice on this lease
            _OptionalResult(conflicting_invoice),   # number used by duplicate
            _OptionalResult(uuid.uuid4()),          # source is the same file
            _RowsResult([line]),                    # duplicate invoice lines
        ],
    )
    client = _make_client(session=session)

    response = client.post(
        f"/api/v1/documents/{lease.id}/review/commit-invoice",
        json=_invoice_review_payload(),
    )

    assert response.status_code == 200
    assert response.json()["invoice_id"] == str(conflicting_invoice.id)
    assert session.commits == 1
    assert conflicting_invoice.invoice_number == "1038"
    assert conflicting_invoice.subtotal == 75.0
    assert line.description == "Design AI Model"
    assert artifact.review_status == "committed"
    assert artifact.review_data["invoice_id"] == str(conflicting_invoice.id)
    # No duplicate invoice row: only 8 header + 5 line provenance rows.
    assert len(session.added) == 8 + 5


def test_invoice_review_commit_rejects_conflicting_invoice_number() -> None:
    """A different invoice may not reuse a number already in the ledger."""
    lease = _lease(document_type="invoice")
    artifact = _artifact(
        upload_id=lease.id,
        review_status=None,
        extraction_confidence=Decimal("0.5000"),
    )
    document = _invoice_review_document()
    vendor = SimpleNamespace(id=uuid.uuid4(), name="Acme Design")
    conflicting_invoice = SimpleNamespace(id=uuid.uuid4(), document_id=uuid.uuid4())
    session = _FakeSession(
        upload_row=lease,
        execute_results=[
            _OptionalResult(artifact),
            _OptionalResult(document),
            _OptionalResult(vendor),
            _OptionalResult(None),                  # no invoice on this lease
            _OptionalResult(conflicting_invoice),   # number already used
            _OptionalResult(None),                  # different source file
        ],
    )
    client = _make_client(session=session)

    response = client.post(
        f"/api/v1/documents/{lease.id}/review/commit-invoice",
        json=_invoice_review_payload(),
    )

    assert response.status_code == 409
    assert session.commits == 0


def test_invoice_review_commit_rejects_committed_review() -> None:
    """A committed invoice review cannot be reopened or overwritten."""
    lease = _lease(document_type="invoice")
    artifact = _artifact(upload_id=lease.id, review_status="committed")
    session = _FakeSession(
        upload_row=lease,
        execute_results=[_OptionalResult(artifact)],
    )
    client = _make_client(session=session)

    response = client.post(
        f"/api/v1/documents/{lease.id}/review/commit-invoice",
        json=_invoice_review_payload(),
    )

    assert response.status_code == 409
    assert session.commits == 0


def test_invoice_review_commit_rejects_high_confidence_without_review() -> None:
    """Trusted extractions cannot be rewritten without an open review."""
    lease = _lease(document_type="invoice")
    artifact = _artifact(
        upload_id=lease.id,
        review_status=None,
        extraction_confidence=Decimal("0.9900"),
    )
    session = _FakeSession(
        upload_row=lease,
        execute_results=[_OptionalResult(artifact)],
    )
    client = _make_client(session=session)

    response = client.post(
        f"/api/v1/documents/{lease.id}/review/commit-invoice",
        json=_invoice_review_payload(),
    )

    assert response.status_code == 409
    assert session.commits == 0


def test_invoice_review_commit_rejects_non_invoice_documents() -> None:
    """The invoice endpoint only accepts invoice documents."""
    lease = _lease(document_type="contract")
    artifact = _artifact(upload_id=lease.id, review_status="pending")
    document = _review_document("contract")
    document.upload_id = lease.id
    session = _FakeSession(
        upload_row=lease,
        execute_results=[_OptionalResult(artifact), _OptionalResult(document)],
    )
    client = _make_client(session=session)

    response = client.post(
        f"/api/v1/documents/{lease.id}/review/commit-invoice",
        json=_invoice_review_payload(),
    )

    assert response.status_code == 422
    assert session.commits == 0


# ---------------------------------------------------------------------------
# DELETE /documents/{id} (explorer cascade delete)
# ---------------------------------------------------------------------------


def test_delete_unknown_document_returns_404() -> None:
    """Unknown lease ids are tenant-scoped 404s."""
    client = _make_client(session=_FakeSession(upload_row=None))
    response = client.delete(f"/api/v1/documents/{uuid.uuid4()}")
    assert response.status_code == 404


def test_delete_rejects_in_flight_upload() -> None:
    """Pending/staged/processing uploads are rejected to avoid worker races."""
    lease = _lease(status=DbUploadStatus.PROCESSING)
    session = _FakeSession(upload_row=lease)
    client = _make_client(session=session)
    response = client.delete(f"/api/v1/documents/{lease.id}")
    assert response.status_code == 409
    assert session.commits == 0
    assert session.deleted == []


def test_delete_removes_document_and_downstream_rows(monkeypatch: Any) -> None:
    """Deleting a completed document cascades through ledger and provenance."""
    lease = _lease()
    artifact = _artifact(upload_id=lease.id)
    document = SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id="default-org",
        upload_id=lease.id,
        gcs_key=lease.gcs_key,
    )
    provenance = SimpleNamespace(id=uuid.uuid4())
    evaluation = SimpleNamespace(id=uuid.uuid4())
    invoice = SimpleNamespace(id=uuid.uuid4())
    invoice_line = SimpleNamespace(id=uuid.uuid4())
    purchase_order = SimpleNamespace(id=uuid.uuid4())
    po_line = SimpleNamespace(id=uuid.uuid4())
    contract = SimpleNamespace(
        id=uuid.uuid4(), document_id=document.id, contract_id=uuid.uuid4()
    )
    version = SimpleNamespace(
        id=uuid.uuid4(),
        contract_id=contract.id,
        source_document_id=document.id,
        parent_version_id=None,
    )
    term = SimpleNamespace(
        id=uuid.uuid4(),
        contract_line_id=uuid.uuid4(),
        amendment_document_id=document.id,
    )
    contract_line = SimpleNamespace(
        id=term.contract_line_id,
        contract_id=contract.id,
        initial_document_id=document.id,
    )
    exception = SimpleNamespace(id=uuid.uuid4())
    session = _FakeSession(
        upload_row=lease,
        execute_results=[
            _OptionalResult(artifact),
            _RowsResult([document]),
            _RowsResult([provenance]),
            _RowsResult([evaluation]),
            _RowsResult([invoice]),
            _RowsResult([invoice_line]),
            _RowsResult([purchase_order]),
            _RowsResult([po_line]),
            _RowsResult([contract]),
            _RowsResult([version]),
            _RowsResult([term]),
            _RowsResult([contract_line]),
            _RowsResult([term]),          # all terms for the candidate line
            _RowsResult([exception]),
            _RowsResult([]),              # null invoices.po_id
            _RowsResult([]),              # null invoices.contract_id
            _RowsResult([]),              # null purchase_orders.contract_id
        ],
    )
    deleted_points: list[str] = []
    monkeypatch.setattr(
        "zellovest_shared.rag.delete_document_points",
        lambda *, tenant_id, document_id: deleted_points.append(document_id),
    )
    client = _make_client(session=session)

    response = client.delete(f"/api/v1/documents/{lease.id}")

    assert response.status_code == 204
    assert session.commits == 1
    for row in (
        provenance,
        evaluation,
        invoice_line,
        invoice,
        po_line,
        purchase_order,
        term,
        version,
        contract_line,
        contract,
        document,
        artifact,
        lease,
    ):
        assert row in session.deleted
    assert exception in session.deleted
    assert deleted_points == [str(document.id)]
