"""Worker tests for the Google Drive ``sync_drive_changes`` task."""

import base64
import os
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://localhost/zellovest")
os.environ.setdefault("ASYNC_DATABASE_URL", "postgresql+asyncpg://localhost/zellovest")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("RAMP_CLIENT_ID", "test-id")
os.environ.setdefault("RAMP_CLIENT_SECRET", "test-secret")
os.environ.setdefault("RAMP_WEBHOOK_SECRET", "whsec-test")
os.environ.setdefault("CREDENTIALS_ENCRYPTION_KEY", base64.b64encode(os.urandom(32)).decode())
os.environ.setdefault("GCS_RAW_BUCKET", "tenant-bucket")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret")

from zellovest_shared.db.models import SyncStatus
from zellovest_workers.tasks import ingestion


class _FakeCheckpoint:
    """Minimal checkpoint row used by the sync engine."""

    def __init__(self) -> None:
        self.status = SyncStatus.PENDING
        self.cursor_token = None
        self.last_success_cursor = None
        self.attempt_count = 0


class _FakeSession:
    """Session double: no DB, just records commits/closes."""

    def __init__(self) -> None:
        self.commits = 0
        self.closed = False

    def execute(self, *_args, **_kwargs):  # type: ignore[no-untyped-def]
        return SimpleNamespace(scalar_one_or_none=lambda: None)

    def add(self, _row) -> None:  # type: ignore[no-untyped-def]
        return None

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        return None

    def close(self) -> None:
        self.closed = True


class _FakeDriveClient:
    """Drive client double with one full-list page chain."""

    def __init__(self, *, changes: bool = False) -> None:
        self.changes = changes
        self.file_page_calls = 0
        self.change_page_calls: list[str] = []
        self.downloaded: list[str] = []
        self.closed = False

    def get_start_page_token(self) -> str:
        return "start-token"

    def list_files(self, folder_id=None, page_size=100, page_token=None):  # type: ignore[no-untyped-def]
        self.file_page_calls += 1
        if page_token is None:
            return [
                {"id": "folder-1", "name": "Contracts", "mimeType": "application/vnd.google-apps.folder"},
                {"id": "pdf-1", "name": "contract.pdf", "mimeType": "application/pdf"},
            ], "page-2"
        return [
            {"id": "img-1", "name": "invoice.png", "mimeType": "image/png"},
            {"id": "sheet-1", "name": "budget.xlsx", "mimeType": "application/vnd.ms-excel"},
        ], None

    def list_changes_page(self, page_token, page_size=100):  # type: ignore[no-untyped-def]
        self.change_page_calls.append(page_token)
        if page_token == "tok-1":
            return [
                {
                    "fileId": "pdf-1",
                    "time": "2026-01-01T00:00:00Z",
                    "file": {
                        "id": "pdf-1",
                        "name": "contract.pdf",
                        "mimeType": "application/pdf",
                    },
                }
            ], "tok-2", None
        return [
            {"fileId": "pdf-1", "removed": True, "time": "2026-01-02T00:00:00Z"},
        ], None, "start-token"

    def download_file(self, file_id: str) -> bytes:
        self.downloaded.append(file_id)
        return b"%PDF-1.4 data"

    def close(self) -> None:
        self.closed = True


def _settings() -> SimpleNamespace:
    """Worker settings with a valid-looking Drive OAuth app."""
    return SimpleNamespace(
        gcs_raw_bucket="tenant-bucket",
        google_cloud_project="test-project",
        google_drive_folder_ids="",
        google_drive_token_url="https://oauth2.googleapis.com/token",
        google_drive_client_id="drive-client",
        google_drive_client_secret="drive-secret",
        credentials_encryption_key=base64.b64encode(b"k" * 32).decode(),
    )


def _patch_engine(monkeypatch, client: _FakeDriveClient, checkpoint: _FakeCheckpoint):
    """Wire the sync engine to fakes and return recorded writes."""
    writes: list[dict] = []
    checkpoint_calls: list[dict] = []
    session = _FakeSession()

    monkeypatch.setattr(ingestion, "_settings", _settings)
    monkeypatch.setattr(ingestion, "get_session_factory", lambda: (lambda: session))
    monkeypatch.setattr(ingestion, "_get_checkpoint", lambda *_args: checkpoint)
    monkeypatch.setattr(
        ingestion,
        "_resolve_drive_auth",
        lambda *_args: {
            "token": "access-token",
            "refresh_token": "refresh-token",
            "expires_at": datetime.now(UTC) + timedelta(hours=1),
            "scopes": ["drive.readonly"],
        },
    )
    monkeypatch.setattr(ingestion, "GoogleDriveClient", lambda **_kwargs: client)
    monkeypatch.setattr(
        ingestion,
        "write_records_gz",
        lambda records, **kwargs: writes.append({"records": records, **kwargs})
        or f"raw/documents/{kwargs['suffix']}.jsonl.gz",
    )
    monkeypatch.setattr(
        ingestion,
        "mark_checkpoint",
        lambda _session, _checkpoint, **kwargs: checkpoint_calls.append(kwargs),
    )
    monkeypatch.setattr(ingestion, "_fan_out_drive_file", lambda *_args, **_kwargs: True)
    return session, writes, checkpoint_calls


def test_sync_drive_changes_task_is_registered() -> None:
    """The exact task name dispatched by the API is registered."""
    from zellovest_workers.celery_app import celery_app

    assert (
        "zellovest.workers.tasks.ingestion.sync_drive_changes" in celery_app.tasks
    )


def test_full_drive_sync_lists_files_and_stores_start_cursor(monkeypatch) -> None:
    """A cursor-less run pages files.list and saves the pre-list start token."""
    client = _FakeDriveClient()
    checkpoint = _FakeCheckpoint()
    session, writes, checkpoint_calls = _patch_engine(monkeypatch, client, checkpoint)

    result = ingestion._sync_drive(
        MagicMock(),
        tenant_id="t1",
        cursor=None,
        sync_id=str(uuid.uuid4()),
        page_size=100,
    )

    assert client.file_page_calls == 2
    assert client.closed is True
    assert result["mode"] == "full"
    assert result["cursor"] == "start-token"
    assert result["records"] == 4
    assert result["processed"] == 3
    assert [len(w["records"]) for w in writes] == [2, 2]
    assert writes[0]["entity_folder"] == "documents"
    assert checkpoint_calls[-1]["status"] == SyncStatus.SUCCESS
    assert checkpoint_calls[-1]["cursor_token"] == "start-token"
    assert session.closed is True


def test_incremental_drive_sync_pages_changes_and_resumes(monkeypatch) -> None:
    """A cursor run follows nextPageToken then stores newStartPageToken."""
    client = _FakeDriveClient(changes=True)
    checkpoint = _FakeCheckpoint()
    session, writes, checkpoint_calls = _patch_engine(monkeypatch, client, checkpoint)

    result = ingestion._sync_drive(
        MagicMock(),
        tenant_id="t1",
        cursor="tok-1",
        sync_id=str(uuid.uuid4()),
        page_size=100,
    )

    assert client.change_page_calls == ["tok-1", "tok-2"]
    assert result["mode"] == "incremental"
    assert result["cursor"] == "start-token"
    assert result["records"] == 2
    assert len(writes) == 2
    assert [c["status"] for c in checkpoint_calls] == [
        SyncStatus.RUNNING,
        SyncStatus.RUNNING,
        SyncStatus.RUNNING,
        SyncStatus.SUCCESS,
    ]
    assert checkpoint_calls[-1]["cursor_token"] == "start-token"
    assert session.closed is True


def test_fan_out_copies_pdf_to_gcs_and_enqueues_document_task(monkeypatch) -> None:
    """PDF/image files are copied to GCS and sent to document_tasks."""
    from zellovest_workers.tasks import document_ocr

    writes: list[dict] = []
    enqueued: list[dict] = []
    monkeypatch.setattr(
        ingestion, "write_bytes", lambda data, **kwargs: writes.append({"data": data, **kwargs})
    )
    monkeypatch.setattr(
        document_ocr,
        "process_document",
        SimpleNamespace(delay=lambda **kwargs: enqueued.append(kwargs)),
    )
    session = _FakeSession()
    client = _FakeDriveClient()

    processed = ingestion._fan_out_drive_file(
        session,
        client,
        _settings(),
        tenant_id="t1",
        file={"id": "pdf-1", "name": "../contract.pdf", "mimeType": "application/pdf"},
    )

    assert processed is True
    assert client.downloaded == ["pdf-1"]
    assert writes[0]["key"] == "drive/t1/pdf-1/contract.pdf"
    assert writes[0]["content_type"] == "application/pdf"
    assert enqueued[0]["gcs_key"] == "drive/t1/pdf-1/contract.pdf"
    assert enqueued[0]["tenant_id"] == "t1"


def test_fan_out_skips_non_document_mime_types(monkeypatch) -> None:
    """Spreadsheets are bronze metadata only (no OCR task)."""
    session = _FakeSession()
    client = _FakeDriveClient()

    processed = ingestion._fan_out_drive_file(
        session,
        client,
        _settings(),
        tenant_id="t1",
        file={"id": "sheet-1", "name": "budget.xlsx", "mimeType": "application/vnd.ms-excel"},
    )

    assert processed is False
    assert client.downloaded == []


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("../contract.pdf", "contract.pdf"),
        ("a/b/invoice.png", "invoice.png"),
        ("", "drive-file"),
    ],
)
def test_safe_drive_filename(raw, expected) -> None:  # type: ignore[no-untyped-def]
    """Drive file names cannot escape their GCS prefix."""
    assert ingestion._safe_drive_filename(raw) == expected
