"""Document Explorer read schemas (uploads + extraction_artifacts surface).

The explorer is a read-only view over the ingestion pipeline output: one
wire row per lease (``uploads``), enriched from the persisted extraction
artifact (``extraction_artifacts``) and the vendor registry for tags.

The UI-facing ``status`` is *derived*, not stored: the upload lease status
plus extraction confidence decide between so the list can present the
PRD §7 lifecycle faithfully (Processing / Extracted / Review Needed / Failed).
"""

from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from zellovest_ingestion.schemas.uploads import DEFAULT_TENANT_ID


class DocumentStatus(str, Enum):
    """Derived explorer pill state (PRD §7 human-in-the-loop lifecycle)."""

    PROCESSING = "processing"
    EXTRACTED = "extracted"
    REVIEW_NEEDED = "review_needed"
    FAILED = "failed"


# Extraction confidence at or above this is trusted for the database;
# below it the document needs human review (PRD §7).
EXTRACTED_CONFIDENCE_THRESHOLD = 0.70


def derived_status(upload_status: str, extraction_confidence: Any) -> DocumentStatus:
    """Map lease status + extraction confidence onto an explorer pill.

    Args:
        upload_status: Raw lease status (pending/staged/processing/completed/failed).
        extraction_confidence: Pipeline extraction confidence, when an artifact
            row exists; ``None`` when the artifact is missing.

    Returns:
        One of the four explorer states:
        - ``failed`` — lease failed
        - ``processing`` — pending/staged/processing lease
        - ``extracted`` — completed lease whose extraction confidence meets
          the review threshold
        - ``review_needed`` — completed lease with missing artifact or
          low-confidence extraction (human verification required)
    """
    if upload_status == "failed":
        return DocumentStatus.FAILED
    if upload_status != "completed":
        return DocumentStatus.PROCESSING
    try:
        confidence = float(extraction_confidence) if extraction_confidence is not None else 0.0
    except (TypeError, ValueError):
        confidence = 0.0
    if confidence >= EXTRACTED_CONFIDENCE_THRESHOLD:
        return DocumentStatus.EXTRACTED
    return DocumentStatus.REVIEW_NEEDED


NORMALIZED_DOC_TYPES: set[str] = {
    "contract",
    "amendment",
    "purchase_order",
    "invoice",
    "policy",
    "other",
}


def normalized_doc_types(raw: str | None) -> list[str]:
    """Parse a comma-separated doc-type list onto allowed wire values.

    Args:
        raw: Comma-separated doc types, e.g. ``"policy,other"``.

    Returns:
        Deduplicated lowercase list of recognized doc types
        (empty when ``raw`` is blank or unrecognized).
    """
    if not raw:
        return []
    types: list[str] = []
    for part in raw.split(","):
        value = part.strip().lower()
        if value in NORMALIZED_DOC_TYPES and value not in types:
            types.append(value)
    return types


class DocumentItem(BaseModel):
    """One explorer list row (lease + extraction summary + vendor tag)."""

    id: UUID
    tenant_id: str = Field(default=DEFAULT_TENANT_ID)
    filename: str
    document_type: str
    document_type_confidence: float | None = None
    classification_method: str | None = None
    status: DocumentStatus
    upload_status: str
    vendor_id: str | None = None
    vendor_name: str | None = None
    gcs_key: str
    mime_type: str
    size_bytes: int
    page_count: int | None = None
    error: str | None = None
    has_artifact: bool = False
    artifact_gcs_key: str | None = None
    route: str | None = None
    file_type: str | None = None
    extraction_method: str | None = None
    extraction_confidence: float | None = None
    text_chars: int | None = None
    uploaded_at: datetime
    updated_at: datetime

    @field_validator("document_type", "upload_status", mode="before")
    @classmethod
    def _normalize_enums(cls, value: Any) -> str:
        """Accept enum inputs (row values) as plain strings."""
        raw = value.value if hasattr(value, "value") else value
        return str(raw).strip().lower()


class DocumentListResponse(BaseModel):
    """Paginated explorer list."""

    documents: list[DocumentItem]
    total: int
    page: int
    page_size: int


class DocumentDetailResponse(DocumentItem):
    """Explorer detail: list row + parsed extraction artifact payload."""

    classification: dict[str, Any] | None = None
    artifact: dict[str, Any] | None = None


class DocumentFileResponse(BaseModel):
    """Short-lived signed GET URL for inline preview + download."""

    document_id: UUID
    url: str
    expires_at: datetime
