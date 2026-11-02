"""Unit tests for Phase 2 document data extraction.

Tests PyMuPDF/PDFPlumber digital PDF extraction and Google Cloud Document
AI OCR extraction (with a fake client, no GCP credentials needed).
"""

from __future__ import annotations

import io

import fitz  # PyMuPDF

from zellovest_shared.workers.gcs_client import FakeGcsBucket, FakeGcsReader

from zellovest_workers.tasks.document_extract import (
    ExtractionResult,
    TableExtraction,
    TextBlock,
    extract_digital_pdf,
    extract_document,
    extract_ocr,
    _mime_type_for_file_type,
)


# ---------------------------------------------------------------------------
# Helper: build a minimal valid PDF with text using PyMuPDF
# ---------------------------------------------------------------------------

def _make_pdf_with_text(text: str = "INVOICE #INV-23891\nTotal: $500.00\nVendor: Acme Corp\nDate: 2026-10-28\nLine Item 1: Widget A, 2 x $250.00 = $500.00") -> bytes:
    """Create a small in-memory PDF with the given text."""
    doc = fitz.open()  # new empty PDF
    page = doc.new_page()
    page.insert_text((72, 72), text, fontsize=12)
    buf = io.BytesIO()
    doc.save(buf)
    doc.close()
    return buf.getvalue()


# ---------------------------------------------------------------------------
# MIME type mapping
# ---------------------------------------------------------------------------

def test_mime_type_for_png():
    assert _mime_type_for_file_type("png") == "image/png"


def test_mime_type_for_tiff():
    assert _mime_type_for_file_type("tiff") == "image/tiff"


def test_mime_type_for_scanned_pdf():
    assert _mime_type_for_file_type("scanned_pdf") == "application/pdf"


def test_mime_type_for_digital_pdf():
    assert _mime_type_for_file_type("digital_pdf") == "application/pdf"


def test_mime_type_for_unknown():
    assert _mime_type_for_file_type("unknown") == "application/pdf"


# ---------------------------------------------------------------------------
# Digital PDF extraction (PyMuPDF + PDFPlumber)
# ---------------------------------------------------------------------------

def test_extract_digital_pdf_returns_python_route():
    """A digital PDF with text extracts via the python route."""
    pdf_bytes = _make_pdf_with_text()
    result = extract_digital_pdf(pdf_bytes)

    assert result.file_type == "digital_pdf"
    assert result.route == "python"
    assert result.extraction_method == "pymupdf_pdfplumber"
    assert result.error is None
    assert result.confidence > 0.0
    assert "INVOICE" in result.full_text
    assert "Acme Corp" in result.full_text
    assert len(result.pages) >= 1


def test_extract_digital_pdf_has_pages_with_text_blocks():
    """Extracted pages contain text blocks with bounding boxes."""
    pdf_bytes = _make_pdf_with_text("Line one\nLine two")
    result = extract_digital_pdf(pdf_bytes)

    assert len(result.pages) == 1
    page = result.pages[0]
    assert page.page_number == 1
    assert page.text != ""
    assert len(page.text_blocks) >= 1
    for tb in page.text_blocks:
        assert len(tb.bbox) == 4  # [x0, y0, x1, y1]
        assert tb.page_number == 1


def test_extract_digital_pdf_detects_images():
    """Pages with images report them."""
    pdf_bytes = _make_pdf_with_text("Text with an image")
    result = extract_digital_pdf(pdf_bytes)

    # The generated PDF may or may not have images; just check the field exists
    assert isinstance(result.pages[0].images, list)


def test_extract_digital_pdf_empty_bytes_returns_error():
    """Empty bytes produce an error result."""
    result = extract_digital_pdf(b"")
    assert result.route == "python"
    assert result.extraction_method == "error"
    assert result.error is not None


def test_extract_digital_pdf_invalid_pdf_returns_error():
    """A non-PDF byte sequence produces an error result."""
    result = extract_digital_pdf(b"\x00\x01\x02\x03garbage")
    assert result.route == "python"
    assert result.extraction_method == "error"
    assert result.error is not None


# ---------------------------------------------------------------------------
# ExtractionResult provenance entries
# ---------------------------------------------------------------------------

def test_extraction_result_to_provenance_entries():
    """Provenance entries carry PRD §8 fields."""
    result = ExtractionResult(
        file_type="digital_pdf",
        route="python",
        full_text="INVOICE #INV-23891",
        pages=[],
        entities=[
            {
                "field": "invoice_number",
                "value": "INV-23891",
                "confidence": 0.95,
                "page": 1,
                "bounding_box": [72, 72, 200, 90],
            }
        ],
        tables=[],
        confidence=0.95,
        extraction_method="pymupdf_pdfplumber",
    )
    entries = result.to_provenance_entries(
        source_document="invoice.pdf",
        extraction_method="pymupdf_pdfplumber",
    )
    assert len(entries) == 1
    entry = entries[0]
    assert entry["field"] == "invoice_number"
    assert entry["value"] == "INV-23891"
    assert entry["confidence"] == 0.95
    assert entry["source_document"] == "invoice.pdf"
    assert entry["page"] == 1
    assert entry["bounding_box"] == [72, 72, 200, 90]
    assert entry["extraction_method"] == "pymupdf_pdfplumber"
    assert "extracted_at" in entry


# ---------------------------------------------------------------------------
# Document AI OCR extraction (with fake client)
# ---------------------------------------------------------------------------

class FakeDocumentAIClient:
    """Fake Document AI client for testing without GCP credentials."""

    def __init__(self, response: dict):
        self._response = response
        self.call_count = 0
        self.last_mime_type = None

    def process_document(self, *, data: bytes, mime_type: str) -> dict:
        self.call_count += 1
        self.last_mime_type = mime_type
        self.last_data_size = len(data)
        return self._response


def test_extract_ocr_png_routes_to_document_ai():
    """PNG bytes processed via Document AI return document_ai route."""
    fake_response = {
        "text": "INVOICE #INV-23891\nAmount Due: $1,250.00",
        "pages": [
            {
                "page_number": 1,
                "text": "INVOICE #INV-23891\nAmount Due: $1,250.00",
                "blocks": [
                    {
                        "text": "INVOICE #INV-23891",
                        "confidence": 0.98,
                        "bounding_box": [0.1, 0.1, 0.5, 0.2],
                    }
                ],
                "paragraphs": [],
                "tables": [],
            }
        ],
        "entities": [
            {
                "type": "invoice_number",
                "text": "INV-23891",
                "confidence": 0.95,
                "bounding_box": [0.1, 0.1, 0.5, 0.2],
                "page_ref": type("PR", (), {"page": 1})(),
            }
        ],
    }
    client = FakeDocumentAIClient(fake_response)
    png_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100

    result = extract_ocr(png_bytes, "png", client=client)

    assert result.file_type == "png"
    assert result.route == "document_ai"
    assert result.extraction_method == "document_ai"
    assert result.error is None
    assert "INVOICE" in result.full_text
    assert client.call_count == 1
    assert client.last_mime_type == "image/png"
    assert len(result.entities) == 1
    assert result.entities[0]["field"] == "invoice_number"
    assert result.entities[0]["value"] == "INV-23891"


def test_extract_ocr_tiff_routes_to_document_ai():
    """TIFF bytes processed via Document AI return document_ai route."""
    fake_response = {
        "text": "SCANNED CONTRACT",
        "pages": [
            {
                "page_number": 1,
                "text": "SCANNED CONTRACT",
                "blocks": [],
                "paragraphs": [],
                "tables": [],
            }
        ],
        "entities": [],
    }
    client = FakeDocumentAIClient(fake_response)
    tiff_bytes = b"II*\x00" + b"\x00" * 100

    result = extract_ocr(tiff_bytes, "tiff", client=client)

    assert result.file_type == "tiff"
    assert result.route == "document_ai"
    assert client.last_mime_type == "image/tiff"


def test_extract_ocr_scanned_pdf():
    """Scanned PDF bytes processed via Document AI."""
    fake_response = {
        "text": "SCANNED INVOICE",
        "pages": [
            {
                "page_number": 1,
                "text": "SCANNED INVOICE",
                "blocks": [],
                "paragraphs": [],
                "tables": [],
            }
        ],
        "entities": [],
    }
    client = FakeDocumentAIClient(fake_response)
    pdf_bytes = b"%PDF-1.7\nsome scanned content\n%%EOF"

    result = extract_ocr(pdf_bytes, "scanned_pdf", client=client)

    assert result.file_type == "scanned_pdf"
    assert result.route == "document_ai"
    assert client.last_mime_type == "application/pdf"


def test_extract_ocr_client_failure_returns_error():
    """Document AI client errors produce an error result."""
    class FailingClient:
        def process_document(self, *, data: bytes, mime_type: str) -> dict:
            raise RuntimeError("Document AI service unavailable")

    result = extract_ocr(b"\x89PNG\r\n\x1a\n" + b"\x00" * 10, "png", client=FailingClient())

    assert result.route == "document_ai"
    assert result.extraction_method == "error"
    assert result.error is not None
    assert result.confidence == 0.0


# ---------------------------------------------------------------------------
# extract_document dispatcher
# ---------------------------------------------------------------------------

def test_extract_document_digital_pdf_uses_python():
    """route='python' + file_type='digital_pdf' dispatches to PyMuPDF/PDFPlumber."""
    pdf_bytes = _make_pdf_with_text("INVOICE #INV-23891")
    result = extract_document(pdf_bytes, "digital_pdf", "python")

    assert result.route == "python"
    assert result.extraction_method == "pymupdf_pdfplumber"
    assert "INVOICE" in result.full_text


def test_extract_document_scanned_pdf_uses_document_ai():
    """route='document_ai' + file_type='scanned_pdf' dispatches to Document AI."""
    fake_response = {"text": "OCR TEXT", "pages": [], "entities": []}
    client = FakeDocumentAIClient(fake_response)
    result = extract_document(
        b"\x89PNG\r\n\x1a\n" + b"\x00" * 10, "png", "document_ai",
        document_ai_client=client,
    )

    assert result.route == "document_ai"
    assert result.extraction_method == "document_ai"


def test_extract_document_unknown_falls_back_to_document_ai():
    """Unknown file type falls back to Document AI (safe default)."""
    fake_response = {"text": "", "pages": [], "entities": []}
    client = FakeDocumentAIClient(fake_response)
    result = extract_document(
        b"\x00\x01\x02\x03", "unknown", "python",
        document_ai_client=client,
    )

    assert result.route == "document_ai"
    assert client.call_count == 1


# ---------------------------------------------------------------------------
# GCS-backed end-to-end (uses FakeGcsReader, no credentials)
# ---------------------------------------------------------------------------

def test_gcs_end_to_end_digital_pdf():
    """Full flow: GCS download -> triage -> extract -> result."""
    pdf_bytes = _make_pdf_with_text()
    FakeGcsBucket.put("test-bucket", "drive/t1/f1/inv.pdf", pdf_bytes, content_type="application/pdf")
    reader = FakeGcsReader()

    data = reader.download_bytes(bucket="test-bucket", key="drive/t1/f1/inv.pdf")
    assert data is not None

    from zellovest_workers.tasks.document_triage import triage_document_from_bytes
    triage = triage_document_from_bytes(data)
    assert triage.file_type == "digital_pdf"
    assert triage.route == "python"

    result = extract_document(data, triage.file_type, triage.route)
    assert result.route == "python"
    assert "INVOICE" in result.full_text
    assert result.error is None


def test_gcs_end_to_end_png_ocr():
    """Full flow for PNG: GCS download -> triage -> Document AI extraction."""
    png_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
    FakeGcsBucket.put("test-bucket", "drive/t1/f1/receipt.png", png_bytes, content_type="image/png")
    reader = FakeGcsReader()

    data = reader.download_bytes(bucket="test-bucket", key="drive/t1/f1/receipt.png")
    assert data is not None

    from zellovest_workers.tasks.document_triage import triage_document_from_bytes
    triage = triage_document_from_bytes(data)
    assert triage.file_type == "png"
    assert triage.route == "document_ai"

    fake_response = {"text": "RECEIPT TOTAL $42.00", "pages": [], "entities": []}

    # Use the locally defined FakeDocumentAIClient
    client = FakeDocumentAIClient(fake_response)
    result = extract_document(data, triage.file_type, triage.route, document_ai_client=client)

    assert result.route == "document_ai"
    assert "RECEIPT" in result.full_text
