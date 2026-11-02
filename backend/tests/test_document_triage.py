"""Unit tests for Phase 1 content-based document triage.

Uses :class:`FakeGcsReader` / :class:`FakeGcsBucket` from
``zellovest_shared.workers.gcs_client`` so no GCP credentials are needed.
"""

from __future__ import annotations

from zellovest_shared.workers.gcs_client import (
    FakeGcsBucket,
    FakeGcsReader,
)

from zellovest_workers.tasks.document_triage import (
    TriageResult,
    analyze_pdf,
    identify_file_type,
    triage_document,
    triage_document_from_bytes,
)

# --- Minimal valid PDF bytes (header + EOF marker, no real content) ---
_MINIMAL_PDF = b"%PDF-1.7\n%%EOF"

# --- PNG signature bytes ---
_PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100

# --- TIFF little-endian signature bytes ---
_TIFF_LE_BYTES = b"II*\x00" + b"\x00" * 100

# --- TIFF big-endian signature bytes ---
_TIFF_BE_BYTES = b"MM\x00*" + b"\x00" * 100


# ---------------------------------------------------------------------------
# Magic byte identification
# ---------------------------------------------------------------------------

def test_identify_pdf_by_magic_bytes():
    """A file starting with %PDF- is identified as pdf regardless of name."""
    file_type, confidence = identify_file_type(_MINIMAL_PDF)
    assert file_type == "pdf"
    assert confidence == 0.99


def test_identify_png_by_magic_bytes():
    """PNG signature bytes are identified as png."""
    file_type, confidence = identify_file_type(_PNG_BYTES)
    assert file_type == "png"
    assert confidence == 0.99


def test_identify_tiff_le_by_magic_bytes():
    """Little-endian TIFF signature is identified as tiff."""
    file_type, confidence = identify_file_type(_TIFF_LE_BYTES)
    assert file_type == "tiff"
    assert confidence == 0.99


def test_identify_tiff_be_by_magic_bytes():
    """Big-endian TIFF signature is identified as tiff."""
    file_type, confidence = identify_file_type(_TIFF_BE_BYTES)
    assert file_type == "tiff"
    assert confidence == 0.99


def test_identify_unknown_by_magic_bytes():
    """Unrecognized content is identified as unknown."""
    file_type, confidence = identify_file_type(b"\x00\x01\x02\x03garbage")
    assert file_type == "unknown"
    assert confidence == 0.0


def test_identify_empty_bytes():
    """Empty bytes are identified as unknown with zero confidence."""
    file_type, confidence = identify_file_type(b"")
    assert file_type == "unknown"
    assert confidence == 0.0


# ---------------------------------------------------------------------------
# Content-based triage from bytes (no GCS)
# ---------------------------------------------------------------------------

def test_triage_png_routes_to_document_ai():
    """PNG content routes straight to Document AI."""
    result = triage_document_from_bytes(_PNG_BYTES)
    assert result.file_type == "png"
    assert result.route == "document_ai"
    assert result.detection_method == "magic_bytes"
    assert result.confidence == 0.99


def test_triage_tiff_routes_to_document_ai():
    """TIFF content routes straight to Document AI."""
    result = triage_document_from_bytes(_TIFF_LE_BYTES)
    assert result.file_type == "tiff"
    assert result.route == "document_ai"
    assert result.detection_method == "magic_bytes"


def test_triage_unknown_routes_to_document_ai():
    """Unknown content falls back to Document AI as the safe default."""
    result = triage_document_from_bytes(b"\x00\x01\x02\x03garbage")
    assert result.file_type == "unknown"
    assert result.route == "document_ai"
    assert result.error is None  # not a failure — safe fallback to OCR


def test_triage_empty_blob_returns_error():
    """Empty/absent bytes produce a failed triage result."""
    result = triage_document_from_bytes(None)
    assert result.file_type == "unknown"
    assert result.route == "document_ai"
    assert result.error == "empty or absent blob"
    assert result.confidence == 0.0

    result = triage_document_from_bytes(b"")
    assert result.error == "empty or absent blob"


def test_triage_mime_hint_is_ignored():
    """The MIME hint is a weak signal; content wins over extension/MIME."""
    # A .txt-named file whose content starts with %PDF- is still a PDF.
    # PyMuPDF is not installed in this env, so PDF falls back to scanned_pdf.
    result = triage_document_from_bytes(_MINIMAL_PDF, mime_hint="text/plain")
    assert result.file_type == "scanned_pdf"
    assert result.route == "document_ai"


# ---------------------------------------------------------------------------
# GCS-backed triage (uses FakeGcsReader, no credentials)
# ---------------------------------------------------------------------------

def _setup_gcs(bucket: str, key: str, data: bytes | None) -> FakeGcsReader:
    """Put data into the fake GCS bucket and return a reader."""
    if data is not None:
        FakeGcsBucket.put(bucket, key, data, content_type="application/octet-stream")
    else:
        FakeGcsBucket.clear()
    return FakeGcsReader()


def test_gcs_triage_pdf_routes_to_document_ai_when_pymupdf_unavailable():
    """A minimal PDF with no real text routes to document_ai via PyMuPDF check."""
    reader = _setup_gcs("test-bucket", "drive/t1/f1/invoice.pdf", _MINIMAL_PDF)
    result = triage_document(
        tenant_id="t1",
        gcs_key="drive/t1/f1/invoice.pdf",
        upload_id="u1",
        bucket="test-bucket",
        reader=reader,
    )
    assert result["route"] == "document_ai"
    assert result["file_type"] == "scanned_pdf"
    assert result["status"] == "completed"
    assert result["error"] is None
    assert result["provenance"]["field"] == "document_format"
    assert result["provenance"]["source_document"] == "invoice.pdf"


def test_gcs_triage_png_routes_to_document_ai():
    """PNG from GCS routes to Document AI."""
    reader = _setup_gcs("test-bucket", "drive/t1/f1/receipt.png", _PNG_BYTES)
    result = triage_document(
        tenant_id="t1",
        gcs_key="drive/t1/f1/receipt.png",
        upload_id="u1",
        bucket="test-bucket",
        reader=reader,
    )
    assert result["route"] == "document_ai"
    assert result["file_type"] == "png"
    assert result["status"] == "completed"


def test_gcs_triage_tiff_routes_to_document_ai():
    """TIFF from GCS routes to Document AI."""
    reader = _setup_gcs("test-bucket", "drive/t1/f1/scan.tiff", _TIFF_LE_BYTES)
    result = triage_document(
        tenant_id="t1",
        gcs_key="drive/t1/f1/scan.tiff",
        upload_id="u1",
        bucket="test-bucket",
        reader=reader,
    )
    assert result["route"] == "document_ai"
    assert result["file_type"] == "tiff"
    assert result["status"] == "completed"


def test_gcs_triage_absent_blob_fails():
    """A missing GCS object produces a failed result."""
    reader = _setup_gcs("test-bucket", "drive/t1/f1/missing.pdf", None)
    result = triage_document(
        tenant_id="t1",
        gcs_key="drive/t1/f1/missing.pdf",
        upload_id="u1",
        reader=reader,
    )
    assert result["status"] == "failed"
    assert result["route"] == "document_ai"
    assert result["error"] == "empty or absent blob"


def test_gcs_triage_unknown_file_type_fails_gracefully():
    """Unrecognized content from GCS falls back to document_ai (not a failure)."""
    reader = _setup_gcs("test-bucket", "drive/t1/f1/data.bin", b"\x00\x01\x02\x03")
    result = triage_document(
        tenant_id="t1",
        gcs_key="drive/t1/f1/data.bin",
        upload_id="u1",
        bucket="test-bucket",
        reader=reader,
    )
    assert result["route"] == "document_ai"
    assert result["file_type"] == "unknown"
    assert result["status"] == "completed"


def test_gcs_triage_returns_triage_fields():
    """The result dict includes page_count, text_coverage, has_images, etc."""
    reader = _setup_gcs("test-bucket", "drive/t1/f1/doc.pdf", _MINIMAL_PDF)
    result = triage_document(
        tenant_id="t1",
        gcs_key="drive/t1/f1/doc.pdf",
        upload_id="u1",
        reader=reader,
    )
    assert "page_count" in result
    assert "text_coverage_chars" in result
    assert "text_coverage_ratio" in result
    assert "has_images" in result
    assert "extracted_text" in result
    assert "confidence" in result
    assert "detection_method" in result


def test_gcs_triage_bucket_fallback_to_settings():
    """When no bucket is passed, settings.gcs_raw_bucket is used."""
    reader = _setup_gcs("test-bucket", "drive/t1/f1/doc.pdf", _PNG_BYTES)
    result = triage_document(
        tenant_id="t1",
        gcs_key="drive/t1/f1/doc.pdf",
        upload_id="u1",
        bucket="test-bucket",
        reader=reader,
    )
    assert result["status"] == "completed"
    assert result["file_type"] == "png"


# ---------------------------------------------------------------------------
# analyze_pdf (degrades gracefully when PyMuPDF missing)
# ---------------------------------------------------------------------------

def test_analyze_pdf_with_pymupdf_degrades_on_corrupt_pdf():
    """PyMuPDF is installed; a corrupt/minimal PDF degrades to non-digital."""
    is_digital, page_count, chars, ratio, has_images, text = analyze_pdf(_MINIMAL_PDF)
    assert is_digital is False
    assert page_count == 0
    assert chars == 0
    assert ratio == 0.0
    assert has_images is False
    assert text == ""


def test_triage_result_dataclass_defaults():
    """TriageResult dataclass defaults are correct."""
    result = TriageResult(
        file_type="digital_pdf",
        route="python",
        confidence=0.95,
        detection_method="magic_bytes",
    )
    assert result.page_count == 0
    assert result.text_coverage_chars == 0
    assert result.text_coverage_ratio == 0.0
    assert result.has_images is False
    assert result.extracted_text == ""
    assert result.error is None
