"""Document data extraction (Phase 2 of the preprocessing pipeline).

Performs actual data extraction based on the route decided by Phase 1 triage:

* route="python" (digital_pdf)  -> PyMuPDF text/layout + PDFPlumber tables
* route="document_ai" (scanned_pdf, tiff, png) -> Google Cloud Document AI OCR

Both paths return a common :class:`ExtractionResult` with per-page text,
tables, images, and extracted entities carrying provenance (page, bounding
box, confidence, extraction_method) per PRD §8.

Document classification (invoice / purchase_order / contract / other) is
intentionally deferred — it is handled separately by keyword classification
in ``document_ocr.classify_document`` and by Jev in a later phase.
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol

import pymupdf
import pdfplumber

from zellovest_shared.logging_conf import get_logger

# from google.cloud import documentai
from google.api_core.client_options import ClientOptions


logger = get_logger(__name__)

# --- Digital PDF text coverage threshold (consistent with Phase 1 triage) ---
_MIN_TEXT_CHARS_PER_PAGE = 40


@dataclass
class TextBlock:
    """A block of extracted text with location and confidence."""

    text: str
    bbox: list[float]  # [x0, y0, x1, y1] in PDF points
    confidence: float = 1.0
    page_number: int = 0


@dataclass
class TableExtraction:
    """A table extracted from a page."""

    data: list[list[str]]  # rows of cells
    bbox: list[float]  # [x0, y0, x1, y1]
    page_number: int = 0


@dataclass
class ImageInfo:
    """An image found on a PDF page."""

    bbox: list[float]  # [x0, y0, x1, y1]
    page_number: int = 0
    xref: int = 0


@dataclass
class PageExtraction:
    """Extraction result for a single page."""

    page_number: int
    text: str = ""
    text_blocks: list[TextBlock] = field(default_factory=list)
    tables: list[TableExtraction] = field(default_factory=list)
    images: list[ImageInfo] = field(default_factory=list)


@dataclass
class ExtractionResult:
    """Common extraction output for both python and document_ai routes.

    Attributes:
        file_type: ``digital_pdf`` | ``scanned_pdf`` | ``tiff`` | ``png`` | ``unknown``.
        route: ``python`` | ``document_ai``.
        full_text: Concatenated text across all pages.
        pages: Per-page extraction results.
        entities: Extracted key-value fields with provenance
            (``field``, ``value``, ``confidence``, ``page``, ``bounding_box``).
        tables: All tables across pages.
        confidence: Overall extraction confidence (0.0-1.0).
        extraction_method: ``pymupdf_pdfplumber`` | ``document_ai`` | ``error``.
        error: Error message when extraction could not complete.
    """

    file_type: str
    route: str
    full_text: str = ""
    pages: list[PageExtraction] = field(default_factory=list)
    entities: list[dict[str, Any]] = field(default_factory=list)
    tables: list[dict[str, Any]] = field(default_factory=list)
    confidence: float = 0.0
    extraction_method: str = "error"
    error: str | None = None

    def to_provenance_entries(
        self, source_document: str, extraction_method: str
    ) -> list[dict[str, Any]]:
        """Convert extracted entities to PRD §8 provenance dicts."""
        entries: list[dict[str, Any]] = []
        now = datetime.now(UTC).isoformat()
        for entity in self.entities:
            entries.append(
                {
                    "field": entity.get("field", ""),
                    "value": entity.get("value", ""),
                    "confidence": entity.get("confidence", 0.0),
                    "source_document": source_document,
                    "page": entity.get("page", 0),
                    "bounding_box": entity.get("bounding_box", []),
                    "extraction_method": extraction_method,
                    "extracted_at": now,
                }
            )
        return entries


class DocumentAIClient(Protocol):
    """Test seam for Google Cloud Document AI processing."""

    def process_document(
        self, *, data: bytes, mime_type: str
    ) -> dict[str, Any]:
        """Run Document AI OCR on raw bytes.

        Args:
            data: Raw document bytes.
            mime_type: MIME type of the document (e.g. ``image/png``,
                ``image/tiff``, ``application/pdf``).

        Returns:
            Raw Document AI response dict.
        """
        ...


class RealDocumentAIClient:
    """Real Document AI client backed by ``google-cloud-documentai``."""

    def __init__(
        self,
        project_id: str,
        location: str,
        processor_id: str,
    ) -> None:
        """Initialize with Document AI processor details.

        Args:
            project_id: GCP project id.
            location: Document AI location (``us``, ``eu``, etc.).
            processor_id: Document AI processor id.
        """
        self._project_id = project_id
        self._location = location
        self._processor_id = processor_id

    def process_document(
        self, *, data: bytes, mime_type: str
    ) -> dict[str, Any]:
        """Process a document through Google Cloud Document AI.
        Args:
            data: Raw document bytes.
            mime_type: MIME type of the document.

        Returns:
            Raw Document AI response dict containing document text,
            entities, tables, and page information.
        """
        from google.api_core.client_options import ClientOptions
        from google.cloud import documentai

        # Document AI is regional: requests must hit the endpoint matching the
        # processor's location. The default endpoint is served by the US
        # deployment and rejects processors in other locations.
        if self._location == "us":
            client = documentai.DocumentProcessorServiceClient()
        else:
            client = documentai.DocumentProcessorServiceClient(
                client_options=ClientOptions(
                    api_endpoint=f"{self._location}-documentai.googleapis.com"
                )
            )
        name = client.processor_path(
            self._project_id, self._location, self._processor_id
        )

        raw_document = documentai.RawDocument(
            content=data, mime_type=mime_type
        )
        request = documentai.ProcessRequest(
            name=name, raw_document=raw_document
        )

        result = client.process_document(request=request)
        document = result.document

        def _bbox(
            poly: Any,
            width: float,
            height: float,
        ) -> list[float]:
            """Convert a BoundingPoly to ``[x0, y0, x1, y1]`` point space.

            Document AI returns normalized vertices (0-1) relative to the
            page; scale them by the page dimensions so the values are
            comparable to the PyMuPDF path (points), per PRD provenance.

            Args:
                poly: ``documentai.BoundingPoly`` (may be empty).
                width: Page width (0/None falls back to normalized scale).
                height: Page height (0/None falls back to normalized scale).

            Returns:
                ``[x0, y0, x1, y1]`` or ``[]`` when no vertices exist.
            """
            vertices = list(poly.normalized_vertices) if poly is not None else []
            if not vertices:
                return []
            xs = [v.x * (width or 1.0) for v in vertices]
            ys = [v.y * (height or 1.0) for v in vertices]
            return [min(xs), min(ys), max(xs), max(ys)]

        pages_payload: list[dict[str, Any]] = []
        entities_payload: list[dict[str, Any]] = []
        page_dims: dict[int, tuple[float, float]] = {}

        for page in document.pages:
            page_number = page.page_number
            width = page.dimension.width if page.dimension.width else 1.0
            height = page.dimension.height if page.dimension.height else 1.0
            page_dims[page_number] = (width, height)

            pages_payload.append(
                {
                    "page_number": page_number,
                    # Page has no "text" field; the page-level layout anchor
                    # carries the full page text.
                    "text": (
                        page.layout.text_anchor.content or ""
                        if page.layout is not None
                        else ""
                    ),
                    "blocks": [
                        {
                            "text": block.layout.text_anchor.content or "",
                            "confidence": block.layout.confidence,
                            "bounding_box": _bbox(
                                block.layout.bounding_poly, width, height
                            ),
                        }
                        for block in page.blocks
                    ],
                    "paragraphs": [
                        {
                            "text": paragraph.layout.text_anchor.content or "",
                            "confidence": paragraph.layout.confidence,
                        }
                        for paragraph in page.paragraphs
                    ],
                    "tables": [
                        {
                            # Plain string rows (never proto objects) so the
                            # dict survives Celery result serialization and
                            # matches the PDFPlumber row contract.
                            "header_rows": [
                                [
                                    cell.layout.text_anchor.content or ""
                                    for cell in row.cells
                                ]
                                for row in table.header_rows
                            ],
                            "body_rows": [
                                [
                                    cell.layout.text_anchor.content or ""
                                    for cell in row.cells
                                ]
                                for row in table.body_rows
                            ],
                        }
                        for table in page.tables
                    ],
                }
            )

        for entity in document.entities:
            page_refs = list(entity.page_anchor.page_refs) if entity.page_anchor is not None else []
            page_index = page_refs[0].page if page_refs else 0
            width, height = page_dims.get(page_index + 1, (1.0, 1.0))
            entities_payload.append(
                {
                    "type": entity.type_ or "",
                    "text": entity.mention_text or "",
                    "confidence": entity.confidence,
                    "bounding_box": _bbox(
                        page_refs[0].bounding_poly if page_refs else None,
                        width,
                        height,
                    ),
                    "page": page_index + 1,
                }
            )

        return {
            "text": document.text or "",
            "pages": pages_payload,
            "entities": entities_payload,
        }


def _mime_type_for_file_type(file_type: str) -> str:
    """Map file type to a MIME type for Document AI."""
    mapping = {
        "png": "image/png",
        "tiff": "image/tiff",
        "scanned_pdf": "application/pdf",
        "digital_pdf": "application/pdf",
        "unknown": "application/pdf",
    }
    return mapping.get(file_type, "application/pdf")


def extract_digital_pdf(
    data: bytes,
) -> ExtractionResult:
    """Extract text, tables, and images from a digital PDF using PyMuPDF + PDFPlumber.

    Opens the PDF from an in-memory stream. PyMuPDF is used for text blocks
    with bounding boxes and image detection; PDFPlumber is used for table
    extraction. Results are merged per page.

    Args:
        data: Raw PDF bytes.

    Returns:
        ExtractionResult with route="python" and extraction_method="pymupdf_pdfplumber".
    """
    try:
        doc = pymupdf.open(stream=data, filetype="pdf")
    except Exception as exc:
        logger.warning("pymupdf_open_failed", error_class=type(exc).__name__)
        return _error_result("digital_pdf", "python", str(exc))

    pages: list[PageExtraction] = []
    full_text_parts: list[str] = []

    # Open PDFPlumber once for table extraction across all pages.
    plumber_pdf = None
    try:
        plumber_pdf = pdfplumber.open(io.BytesIO(data))
    except Exception as exc:
        logger.warning("pdfplumber_open_failed", error_class=type(exc).__name__)

    try:
        for page_index, page in enumerate(doc):
            page_number = page_index + 1
            page_text = page.get_text() or ""
            full_text_parts.append(page_text)

            # Text blocks with bounding boxes via PyMuPDF
            text_blocks: list[TextBlock] = []
            try:
                blocks = page.get_text("blocks")
                for block in blocks:
                    x0, y0, x1, y1, text, block_no, block_type = block
                    if block_type == 0 and text.strip():  # text block
                        text_blocks.append(
                            TextBlock(
                                text=text.strip(),
                                bbox=[x0, y0, x1, y1],
                                page_number=page_number,
                            )
                        )
            except Exception as exc:
                logger.warning(
                    "pymupdf_blocks_failed",
                    page_number=page_number,
                    error_class=type(exc).__name__,
                )

            # Images on the page via PyMuPDF
            images: list[ImageInfo] = []
            try:
                for img_index, img in enumerate(page.get_images(full=True)):
                    xref = img[0]
                    try:
                        rects = page.get_image_rects(xref)
                        for rect in rects:
                            images.append(
                                ImageInfo(
                                    bbox=[rect.x0, rect.y0, rect.x1, rect.y1],
                                    page_number=page_number,
                                    xref=xref,
                                )
                            )
                    except Exception:
                        pass
            except Exception as exc:
                logger.warning(
                    "pymupdf_images_failed",
                    page_number=page_number,
                    error_class=type(exc).__name__,
                )

            # Tables via PDFPlumber (opened once above)
            tables: list[TableExtraction] = []
            try:
                if plumber_pdf is not None and page_index < len(plumber_pdf.pages):
                    plumber_page = plumber_pdf.pages[page_index]
                    plumber_tables = plumber_page.extract_tables()
                    if plumber_tables:  # only look for bboxes when tables exist
                        table_bboxes = plumber_page.find_tables()
                        for table_index, table_data in enumerate(plumber_tables):
                            if not table_data:
                                continue
                            bbox = [0, 0, 0, 0]
                            if table_index < len(table_bboxes):
                                tb = table_bboxes[table_index]
                                bbox = [tb.x0, tb.top, tb.x1, tb.bottom]
                            tables.append(
                                TableExtraction(
                                    data=table_data,
                                    bbox=bbox,
                                    page_number=page_number,
                                )
                            )
            except AttributeError:
                # pdfplumber raises AttributeError on pages without extractable
                # table structures; this is normal, not a failure.
                logger.debug(
                    "pdfplumber_no_tables_on_page",
                    page_number=page_number,
                )
            except Exception as exc:
                logger.warning(
                    "pdfplumber_tables_failed",
                    page_number=page_number,
                    error_class=type(exc).__name__,
                )

            pages.append(
                PageExtraction(
                    page_number=page_number,
                    text=page_text,
                    text_blocks=text_blocks,
                    tables=tables,
                    images=images,
                )
            )

        doc.close()

    except Exception as exc:
        logger.warning("pymupdf_iteration_failed", error_class=type(exc).__name__)
        try:
            doc.close()
        except Exception:
            pass
        return _error_result("digital_pdf", "python", str(exc))
    finally:
        if plumber_pdf is not None:
            try:
                plumber_pdf.close()
            except Exception:
                pass

    full_text = "\n".join(full_text_parts)
    total_chars = len(full_text.strip())
    confidence = min(0.99, max(0.5, total_chars / 1000.0)) if total_chars > 0 else 0.0

    # Flatten tables into dict form
    tables_dict: list[dict[str, Any]] = []
    for page in pages:
        for table in page.tables:
            tables_dict.append(
                {
                    "page": table.page_number,
                    "data": table.data,
                    "bounding_box": table.bbox,
                }
            )

    return ExtractionResult(
        file_type="digital_pdf",
        route="python",
        full_text=full_text,
        pages=pages,
        entities=[],  # entity extraction is deferred to Jev / later phase
        tables=tables_dict,
        confidence=confidence,
        extraction_method="pymupdf_pdfplumber",
    )

def extract_ocr(
    data: bytes,
    file_type: str,
    *,
    client: DocumentAIClient | None = None,
) -> ExtractionResult:
    """Extract data from an image-based document via Google Cloud Document AI.

    Handles scanned PDFs, PNG, and TIFF files. Falls back gracefully when
    Document AI is not configured or the client raises an error.

    Args:
        data: Raw document bytes.
        file_type: ``scanned_pdf`` | ``tiff`` | ``png`` | ``unknown``.
        client: Injectible Document AI client. Defaults to a real client
            built from settings (``DOCUMENT_AI_PROJECT_ID`` etc.).

    Returns:
        ExtractionResult with route="document_ai" and extraction_method="document_ai".
    """
    from zellovest_shared.config import get_settings

    if client is None:
        try:
            settings = get_settings()
            client = RealDocumentAIClient(
                project_id=settings.document_ai_project_id,
                location=settings.document_ai_location,
                processor_id=settings.document_ai_processor_id,
            )
        except Exception as exc:
            logger.warning(
                "document_ai_not_configured",
                error_class=type(exc).__name__,
            )
            return _error_result(
                file_type, "document_ai", "Document AI not configured"
            )

    mime_type = _mime_type_for_file_type(file_type)

    try:
        response = client.process_document(data=data, mime_type=mime_type)
    except Exception as exc:
        logger.warning(
            "document_ai_process_failed",
            file_type=file_type,
            error_class=type(exc).__name__,
        )
        return _error_result(file_type, "document_ai", str(exc))

    full_text = response.get("text", "")
    pages: list[PageExtraction] = []

    for page_data in response.get("pages", []):
        page_number = page_data.get("page_number", 0)
        page_text = page_data.get("text", "")

        text_blocks: list[TextBlock] = []
        for block in page_data.get("blocks", []):
            bbox = block.get("bounding_box", [])
            text_blocks.append(
                TextBlock(
                    text=block.get("text", ""),
                    bbox=bbox,
                    confidence=block.get("confidence", 0.0),
                    page_number=page_number,
                )
            )

        tables: list[TableExtraction] = []
        for table_data in page_data.get("tables", []):
            tables.append(
                TableExtraction(
                    data=table_data.get("body_rows", []),
                    bbox=[0, 0, 0, 0],  # Document AI doesn't always return table bbox
                    page_number=page_number,
                )
            )

        pages.append(
            PageExtraction(
                page_number=page_number,
                text=page_text,
                text_blocks=text_blocks,
                tables=tables,
            )
        )

    # Convert Document AI entities to our common entity format
    entities: list[dict[str, Any]] = []
    for entity in response.get("entities", []):
        entities.append(
            {
                "field": entity.get("type", ""),
                "value": entity.get("text", ""),
                "confidence": entity.get("confidence", 0.0),
                "page": entity.get("page", 0),
                "bounding_box": entity.get("bounding_box", []),
            }
        )

    # Flatten tables
    tables_dict: list[dict[str, Any]] = []
    for page in pages:
        for table in page.tables:
            tables_dict.append(
                {
                    "page": table.page_number,
                    "data": table.data,
                    "bounding_box": table.bbox,
                }
            )

    total_chars = len(full_text.strip())
    confidence = min(0.99, max(0.5, total_chars / 1000.0)) if total_chars > 0 else 0.0

    return ExtractionResult(
        file_type=file_type,
        route="document_ai",
        full_text=full_text,
        pages=pages,
        entities=entities,
        tables=tables_dict,
        confidence=confidence,
        extraction_method="document_ai",
    )


def extract_document(
    data: bytes,
    file_type: str,
    route: str,
    *,
    document_ai_client: DocumentAIClient | None = None,
) -> ExtractionResult:
    """Dispatch to the correct extraction method based on triage route.

    Args:
        data: Raw document bytes.
        file_type: ``digital_pdf`` | ``scanned_pdf`` | ``tiff`` | ``png`` | ``unknown``.
        route: ``python`` (digital PDF) | ``document_ai`` (OCR).
        document_ai_client: Optional injected Document AI client for testing.

    Returns:
        ExtractionResult from the appropriate extraction path.
    """
    if route == "python" and file_type == "digital_pdf":
        return extract_digital_pdf(data)
    if route == "document_ai":
        return extract_ocr(
            data, file_type, client=document_ai_client
        )
    # Unknown or mismatched: fall back to Document AI as the safe default
    return extract_ocr(
        data, file_type, client=document_ai_client
    )


def _error_result(
    file_type: str, route: str, error: str
) -> ExtractionResult:
    """Build a standardized failure ExtractionResult."""
    return ExtractionResult(
        file_type=file_type,
        route=route,
        full_text="",
        pages=[],
        entities=[],
        tables=[],
        confidence=0.0,
        extraction_method="error",
        error=error,
    )
