"""Tests for document vendor write-through after extraction."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

from zellovest_workers.tasks.document_verify import _link_document_vendor


class _Session:
    """Minimal session double for the document vendor-link helper."""

    def __init__(self, upload: object | None) -> None:
        """Store the upload returned by ``get``."""
        self.upload = upload

    def get(self, model: object, upload_id: uuid.UUID) -> object | None:
        """Return the configured upload row."""
        return self.upload


def test_link_document_vendor_updates_document_and_upload() -> None:
    """A resolved vendor is copied to both explorer source rows."""
    vendor_id = uuid.uuid4()
    upload = SimpleNamespace(vendor_id=None)
    document = SimpleNamespace(upload_id=uuid.uuid4(), vendor_id=None)

    _link_document_vendor(
        _Session(upload),
        document=document,
        vendor_id=vendor_id,
    )

    assert document.vendor_id == vendor_id
    assert upload.vendor_id == str(vendor_id)


def test_link_document_vendor_does_not_clear_existing_links() -> None:
    """An unresolved vendor leaves existing document and upload links intact."""
    vendor_id = uuid.uuid4()
    upload = SimpleNamespace(vendor_id=str(vendor_id))
    document = SimpleNamespace(upload_id=uuid.uuid4(), vendor_id=vendor_id)

    _link_document_vendor(
        _Session(upload),
        document=document,
        vendor_id=None,
    )

    assert document.vendor_id == vendor_id
    assert upload.vendor_id == str(vendor_id)
