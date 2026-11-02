"""Content-based document triage (Phase 1 of the preprocessing pipeline).

Inspects raw object bytes downloaded from the GCS bronze bucket to identify
the document format *without trusting filename extensions or MIME types*,
then decides the extraction route:

* digital_pdf  -> PyMuPDF / PDFPlumber deterministic extraction (route "python")
* scanned_pdf  -> Google Cloud Document AI OCR (route "document_ai")
* tiff / png   -> Google Cloud Document AI OCR (route "document_ai")
* unknown      -> Document AI as safe default, flagged for review

Only PDFs undergo the digital-vs-scanned check (PyMuPDF text-coverage
analysis). PNG and TIFF are image formats by definition and route straight
to OCR.

Designed as a drop-in replacement for the inline triage inside
``document_ocr.process_document``: the existing Celery task signature,
upload-lease bookkeeping, and return shape are preserved.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

import pymupdf as fitz  # PyMuPDF — required dependency for PDF text-coverage analysis

from zellovest_shared.logging_conf import get_logger

logger = get_logger(__name__)

# --- Magic byte signatures (inspected on the first bytes of file content) ---
PDF_SIGNATURE = b"%PDF-"
TIFF_LE_SIGNATURE = b"II*\x00"   # little-endian TIFF
TIFF_BE_SIGNATURE = b"MM\x00*"   # big-endian TIFF
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"

# --- Thresholds for digital-vs-scanned PDF determination ---
_MIN_TEXT_CHARS_PER_PAGE = 40      # chars of extractable text per page to count as "has text"
_MIN_TEXT_COVERAGE_RATIO = 0.70    # fraction of pages that must have text for "digital"
_MIN_TOTAL_TEXT_CHARS = 100        # minimum total extractable text across the document


@dataclass(frozen=True)
class TriageResult:
    """Outcome of content-based document triage.

    Attributes:
        file_type: ``digital_pdf`` | ``scanned_pdf`` | ``tiff`` | ``png`` | ``unknown``.
        route: ``python`` (deterministic libs) | ``document_ai`` (OCR) | ``unknown``.
        confidence: Detection confidence from 0.0 to 1.0.
        detection_method: How the decision was made (``magic_bytes`` etc.).
        page_count: Number of pages (PDFs only; 0 otherwise).
        text_coverage_chars: Total extractable text characters (PDFs only).
        text_coverage_ratio: Fraction of pages with meaningful text (PDFs only).
        has_images: Whether any page contains embedded images (PDFs only).
        extracted_text: Extracted text (digital PDFs only; empty otherwise).
        error: Error message when triage could not complete.
    """

    file_type: str
    route: str
    confidence: float
    detection_method: str
    page_count: int = 0
    text_coverage_chars: int = 0
    text_coverage_ratio: float = 0.0
    has_images: bool = False
    extracted_text: str = ""
    error: str | None = None


class GcsObjectReader(Protocol):
    """Test seam for downloading object bytes from GCS."""

    def download_bytes(self, *, bucket: str, key: str) -> bytes | None:
        """Return object bytes, or None when the object is absent."""
        ...


def identify_file_type(data: bytes) -> tuple[str, float]:
    """Identify file type from magic bytes (first 16 bytes of content).

    This intentionally ignores filename extensions and MIME types. A file
    named ``invoice.txt`` that begins with ``%PDF-`` is still treated as a
    PDF.

    Args:
        data: Raw file bytes.

    Returns:
        Tuple of (file_type, confidence). file_type is one of:
        ``pdf``, ``tiff``, ``png``, ``unknown``.
    """
    if not data:
        return "unknown", 0.0

    header = data[:16]

    if header.startswith(PDF_SIGNATURE):
        return "pdf", 0.99
    if header.startswith(TIFF_LE_SIGNATURE) or header.startswith(TIFF_BE_SIGNATURE):
        return "tiff", 0.99
    if header.startswith(PNG_SIGNATURE):
        return "png", 0.99

    return "unknown", 0.0


def analyze_pdf(data: bytes) -> tuple[bool, int, int, float, bool, str]:
    """Analyze a PDF to determine if it is digital (text-based) or scanned.

    Opens the PDF from an in-memory stream with PyMuPDF (fitz), then per
    page checks extractable text length and embedded images.

    Args:
        data: Raw PDF bytes.

    Returns:
        Tuple of
        (is_digital, page_count, text_chars, text_ratio, has_images, text).
        Returns all-false/zero values when the PDF cannot be opened or
        analyzed (corrupt, password-protected, etc.).
    """
    try:
        doc = fitz.open(stream=data, filetype="pdf")
    except Exception as exc:
        logger.warning("pdf_open_failed", error_class=type(exc).__name__)
        return False, 0, 0, 0.0, False, ""

    try:
        page_count = len(doc)
        if page_count == 0:
            doc.close()
            return False, 0, 0, 0.0, False, ""

        total_text_chars = 0
        pages_with_text = 0
        has_images = False
        text_parts: list[str] = []

        for page in doc:
            page_text = page.get_text() or ""
            text_parts.append(page_text)
            page_char_count = len(page_text.strip())
            if page_char_count >= _MIN_TEXT_CHARS_PER_PAGE:
                pages_with_text += 1
                total_text_chars += page_char_count
            if page.get_images():
                has_images = True

        doc.close()

        text = "\n".join(text_parts)
        text_ratio = pages_with_text / page_count if page_count > 0 else 0.0

        is_digital = (
            total_text_chars >= _MIN_TOTAL_TEXT_CHARS
            and text_ratio >= _MIN_TEXT_COVERAGE_RATIO
        )

        return is_digital, page_count, total_text_chars, text_ratio, has_images, text

    except Exception as exc:  # corrupt content, etc.
        logger.warning("pdf_analysis_failed", error_class=type(exc).__name__)
        try:
            doc.close()
        except Exception:
            pass
        return False, 0, 0, 0.0, False, ""


def triage_document_from_bytes(
    data: bytes | None,
    mime_hint: str | None = None,
) -> TriageResult:
    """Decide extraction route from raw bytes (content-based, not extension-based).

    Args:
        data: Downloaded object bytes (None when the blob is absent).
        mime_hint: Stored MIME type (weak signal; ignored for format decision).

    Returns:
        TriageResult with route, file_type, confidence, and PDF signals.
    """
    del mime_hint  # content wins over MIME; hint kept for signature compatibility

    if not data:
        return TriageResult(
            file_type="unknown",
            route="document_ai",
            confidence=0.0,
            detection_method="error",
            error="empty or absent blob",
        )

    # Step 1: magic-byte identification
    file_type, confidence = identify_file_type(data)

    if file_type == "png":
        return TriageResult(
            file_type="png",
            route="document_ai",
            confidence=confidence,
            detection_method="magic_bytes",
        )

    if file_type == "tiff":
        return TriageResult(
            file_type="tiff",
            route="document_ai",
            confidence=confidence,
            detection_method="magic_bytes",
        )

    if file_type == "pdf":
        # Step 2: digital vs scanned determination via PyMuPDF text coverage
        try:
            (
                is_digital,
                page_count,
                text_chars,
                text_ratio,
                has_images,
                text,
            ) = analyze_pdf(data)
        except Exception as exc:  # corrupt PDF, password-protected, etc.
            logger.warning("pdf_analysis_failed", error_class=type(exc).__name__)
            return TriageResult(
                file_type="scanned_pdf",
                route="document_ai",
                confidence=min(confidence, 0.95),
                detection_method="magic_bytes",
                page_count=0,
                text_coverage_chars=0,
                text_coverage_ratio=0.0,
                has_images=False,
                extracted_text="",
            )

        if is_digital:
            return TriageResult(
                file_type="digital_pdf",
                route="python",
                confidence=min(confidence, 0.95),
                detection_method="magic_bytes",
                page_count=page_count,
                text_coverage_chars=text_chars,
                text_coverage_ratio=text_ratio,
                has_images=has_images,
                extracted_text=text,
            )
        return TriageResult(
            file_type="scanned_pdf",
            route="document_ai",
            confidence=min(confidence, 0.95),
            detection_method="magic_bytes",
            page_count=page_count,
            text_coverage_chars=text_chars,
            text_coverage_ratio=text_ratio,
            has_images=has_images,
            extracted_text=text,
        )

    # Unknown file type: fall back to Document AI as the safe default.
    # This is not a failure — triage succeeded, we just could not identify
    # the format, so we route to OCR as the conservative choice.
    return TriageResult(
        file_type="unknown",
        route="document_ai",
        confidence=0.0,
        detection_method="magic_bytes",
    )


def triage_document(
    tenant_id: str,
    gcs_key: str,
    upload_id: str | None = None,
    document_type_hint: str | None = None,
    *,
    bucket: str | None = None,
    reader: GcsObjectReader | None = None,
) -> dict[str, Any]:
    """Download from GCS, run content-based triage, and return a result dict.

    This is the GCS-backed entry point used by the Celery worker. It
    downloads the whole object from the bronze bucket, inspects its content,
    decides the extraction route, and returns a dict shaped to slot into the
    existing ``process_document`` return value.

    Args:
        tenant_id: Owning tenant (used for structured logging).
        gcs_key: Verified GCS object key (from the lease row, never client
            supplied).
        upload_id: Lease row id (bookkeeping is handled by the caller).
        document_type_hint: Uploader-supplied type hint (not used for format
            identification).
        bucket: Override bucket name; defaults to ``gcs_raw_bucket`` from
            settings.
        reader: Injectible ``GcsObjectReader``; defaults to
            :class:`GcsStorageReader`. Pass :class:`FakeGcsReader` in tests.

    Returns:
        Dict with route, file_type, confidence, provenance, and PDF signals,
        shaped to be merged into ``process_document``'s return value.
    """
    from zellovest_shared.config import get_settings
    from zellovest_shared.workers.gcs_client import GcsStorageReader

    if reader is None:
        reader = GcsStorageReader()

    if bucket is None:
        try:
            bucket = get_settings().gcs_raw_bucket
        except Exception:
            bucket = ""

    if not bucket:
        logger.error(
            "gcs_bucket_not_configured",
            tenant_id=tenant_id,
            gcs_key=gcs_key,
        )
        return _error_result_dict(
            tenant_id=tenant_id,
            gcs_key=gcs_key,
            upload_id=upload_id,
            error="GCS bucket not configured",
        )

    data = reader.download_bytes(bucket=bucket, key=gcs_key)
    result = triage_document_from_bytes(data)

    filename = gcs_key.rsplit("/", 1)[-1]
    provenance = {
        "field": "document_format",
        "value": result.file_type,
        "confidence": result.confidence,
        "source_document": filename,
        "extraction_method": result.detection_method,
        "extracted_at": datetime.now(UTC).isoformat(),
    }

    return {
        "tenant_id": tenant_id,
        "gcs_key": gcs_key,
        "upload_id": upload_id,
        "route": result.route,
        "file_type": result.file_type,
        "confidence": result.confidence,
        "detection_method": result.detection_method,
        "document_type": "other",  # document classification is a separate step
        "provenance": provenance,
        "page_count": result.page_count,
        "text_coverage_chars": result.text_coverage_chars,
        "text_coverage_ratio": result.text_coverage_ratio,
        "has_images": result.has_images,
        "extracted_text": result.extracted_text,
        "status": "failed" if result.error else "completed",
        "error": result.error,
    }


def _error_result_dict(
    tenant_id: str,
    gcs_key: str,
    upload_id: str | None,
    error: str,
) -> dict[str, Any]:
    """Build a standardized failure result dict."""
    filename = gcs_key.rsplit("/", 1)[-1]
    return {
        "tenant_id": tenant_id,
        "gcs_key": gcs_key,
        "upload_id": upload_id,
        "route": "document_ai",
        "file_type": "unknown",
        "confidence": 0.0,
        "detection_method": "error",
        "document_type": "other",
        "provenance": {
            "field": "document_format",
            "value": "unknown",
            "confidence": 0.0,
            "source_document": filename,
            "extraction_method": "error",
            "extracted_at": datetime.now(UTC).isoformat(),
        },
        "page_count": 0,
        "text_coverage_chars": 0,
        "text_coverage_ratio": 0.0,
        "has_images": False,
        "extracted_text": "",
        "status": "failed",
        "error": error,
    }
