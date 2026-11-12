"""Tests for upload lifecycle terminal state guards and maintenance janitor."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from zellovest_shared.db.models import (
    Document as DocumentRow,
    ExtractionArtifact,
    Upload as UploadRow,
    UploadStatus as DbUploadStatus,
)
from zellovest_workers.tasks.document_classify import classify_upload
from zellovest_workers.tasks.document_index import index_document_task
from zellovest_workers.tasks.document_ocr import _mark_upload, process_document
from zellovest_workers.tasks.document_promote import promote_document
from zellovest_workers.tasks.maintenance import (
    mark_expired_upload_rows,
    purge_expired_upload_rows,
)


def _make_upload(status: DbUploadStatus = DbUploadStatus.PENDING, **kwargs: Any) -> UploadRow:
    """Helper to build an in-memory UploadRow."""
    now = datetime.now(UTC)
    defaults = {
        "id": uuid.uuid4(),
        "tenant_id": "test-org",
        "vendor_id": None,
        "filename": "invoice.pdf",
        "gcs_key": f"uploads/test-org/invoice/{uuid.uuid4().hex}/invoice.pdf",
        "mime_type": "application/pdf",
        "size_expected": 1234,
        "status": status,
        "document_type": "invoice",
        "created_at": now,
        "updated_at": now,
        "expires_at": None,
        "error": None,
    }
    defaults.update(kwargs)
    row = UploadRow()
    for k, v in defaults.items():
        setattr(row, k, v)
    return row


# --- 1. Maintenance Janitor Tests ---


def test_mark_expired_upload_rows_executes_sql() -> None:
    """mark_expired_upload_rows executes the update statement."""
    mock_engine = MagicMock()
    mock_conn = MagicMock()
    mock_result = MagicMock()
    mock_result.rowcount = 3
    mock_conn.execute.return_value = mock_result
    mock_engine.begin.return_value.__enter__.return_value = mock_conn

    with patch("zellovest_workers.tasks.maintenance.get_sync_engine", return_value=mock_engine):
        marked = mark_expired_upload_rows()

    assert marked == 3
    mock_conn.execute.assert_called_once()
    sql_text = str(mock_conn.execute.call_args[0][0].text)
    assert "UPDATE uploads" in sql_text
    assert "status = 'failed'" in sql_text
    assert "expires_at < now()" in sql_text


def test_purge_expired_upload_rows_purges_older_than_1_hour() -> None:
    """purge_expired_upload_rows calls mark first, then selects & deletes >1h expired rows."""
    mock_engine = MagicMock()
    mock_conn = MagicMock()
    mock_conn.execute.side_effect = [
        MagicMock(rowcount=2),  # mark_expired_upload_rows
        [("uploads/test-org/invoice/1/a.pdf",), ("uploads/test-org/invoice/2/b.pdf",)],  # select keys
        MagicMock(rowcount=2),  # delete uploads
    ]
    mock_engine.begin.return_value.__enter__.return_value = mock_conn

    mock_reader = MagicMock()
    mock_reader.delete_object.return_value = True

    with (
        patch("zellovest_workers.tasks.maintenance.get_sync_engine", return_value=mock_engine),
        patch("zellovest_workers.tasks.maintenance.GcsStorageReader", return_value=mock_reader),
        patch("zellovest_shared.config.get_settings") as mock_settings,
    ):
        mock_settings.return_value.gcs_raw_bucket = "test-bucket"
        res = purge_expired_upload_rows(batch_size=100)

    assert res["deleted"] == 2
    assert res["orphans_removed"] == 2
    assert mock_reader.delete_object.call_count == 2


# --- 2. Terminal State Guard Tests ---


def test_mark_upload_does_not_overwrite_completed() -> None:
    """_mark_upload never overwrites an already COMPLETED row with FAILED."""
    upload = _make_upload(status=DbUploadStatus.COMPLETED)
    mock_session = MagicMock()
    mock_session.get.return_value = upload

    with (
        patch("zellovest_workers.tasks.document_ocr.get_sync_engine"),
        patch("zellovest_workers.tasks.document_ocr.Session", return_value=mock_session),
    ):
        mock_session.__enter__.return_value = mock_session
        _mark_upload(str(upload.id), DbUploadStatus.FAILED, "error during late stage")

    assert upload.status == DbUploadStatus.COMPLETED
    mock_session.commit.assert_not_called()


def test_process_document_skips_if_upload_already_failed() -> None:
    """process_document does no download or extraction if the upload is already marked FAILED."""
    upload = _make_upload(status=DbUploadStatus.FAILED)
    mock_session = MagicMock()
    mock_session.get.return_value = upload

    with (
        patch("zellovest_workers.tasks.document_ocr.get_sync_engine"),
        patch("zellovest_workers.tasks.document_ocr.Session", return_value=mock_session),
        patch("zellovest_workers.tasks.document_ocr._download_blob") as mock_download,
    ):
        mock_session.__enter__.return_value = mock_session
        result = process_document(
            tenant_id="test-org",
            gcs_key=upload.gcs_key,
            upload_id=str(upload.id),
        )

    assert result["status"] == "skipped"
    assert result["reason"] == "upload already marked failed"
    mock_download.assert_not_called()


def test_classify_upload_skips_if_upload_already_failed() -> None:
    """classify_upload skips classification if the upload is marked FAILED."""
    upload = _make_upload(status=DbUploadStatus.FAILED)
    artifact = ExtractionArtifact()
    artifact.text_snippet = "Some text snippet"

    with (
        patch("zellovest_workers.tasks.document_classify._load_inputs", return_value=(upload, artifact)),
        patch("zellovest_workers.tasks.document_classify.run_classification") as mock_run_classify,
    ):
        result = classify_upload(tenant_id="test-org", upload_id=str(upload.id))

    assert result["status"] == "skipped"
    assert result["reason"] == "upload already marked failed"
    mock_run_classify.assert_not_called()


def test_promote_document_skips_if_upload_already_failed() -> None:
    """promote_document does not create a document or enqueue indexing if FAILED."""
    upload = _make_upload(status=DbUploadStatus.FAILED)
    mock_session = MagicMock()
    mock_session.get.return_value = upload

    with (
        patch("zellovest_workers.tasks.document_promote.get_sync_engine"),
        patch("zellovest_workers.tasks.document_promote.Session", return_value=mock_session),
        patch("zellovest_workers.tasks.document_index.index_document_task") as mock_index_task,
    ):
        mock_session.__enter__.return_value = mock_session
        result = promote_document(
            tenant_id="test-org",
            upload_id=str(upload.id),
            document_type="invoice",
        )

    assert result["status"] == "skipped"
    assert result["reason"] == "upload already marked failed"
    mock_index_task.delay.assert_not_called()


def test_index_document_task_skips_and_does_not_overwrite_failed() -> None:
    """index_document_task skips indexing if upload is FAILED and never sets COMPLETED."""
    upload = _make_upload(status=DbUploadStatus.FAILED)
    doc_id = uuid.uuid4()
    doc = DocumentRow()
    doc.id = doc_id
    doc.tenant_id = "test-org"
    doc.upload_id = upload.id
    doc.filename = "invoice.pdf"
    doc.document_type = "invoice"
    doc.vendor_id = None

    mock_session = MagicMock()
    mock_session.get.side_effect = lambda model, ident: doc if model == DocumentRow else upload

    with (
        patch("zellovest_workers.tasks.document_index.get_sync_engine"),
        patch("zellovest_workers.tasks.document_index.Session", return_value=mock_session),
        patch("zellovest_workers.tasks.document_index.index_document") as mock_index,
    ):
        mock_session.__enter__.return_value = mock_session
        result = index_document_task(tenant_id="test-org", document_id=str(doc_id))

    assert result["status"] == "skipped"
    assert result["reason"] == "upload already marked failed"
    assert upload.status == DbUploadStatus.FAILED
    mock_index.assert_not_called()
