"""Document Explorer and human contract-review schemas.

The explorer returns one wire row per lease (``uploads``), enriched from the
persisted extraction artifact (``extraction_artifacts``) and vendor registry.
The review command schemas validate corrected commercial terms before commit.

The UI-facing ``status`` is *derived*, not stored: the upload lease status
plus extraction confidence decide between so the list can present the
PRD §7 lifecycle faithfully (Processing / Extracted / Review Needed / Failed).
"""

from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

from zellovest_ingestion.schemas.uploads import DEFAULT_TENANT_ID


class DocumentStatus(str, Enum):
    """Derived explorer pill state (PRD §7 human-in-the-loop lifecycle)."""

    PROCESSING = "processing"
    EXTRACTED = "extracted"
    REVIEW_NEEDED = "review_needed"
    FAILED = "failed"


# Extraction confidence at or above this is trusted for the database;
# below it the document needs human review (PRD §7).
EXTRACTED_CONFIDENCE_THRESHOLD = 0.80


def derived_status(
    upload_status: str,
    extraction_confidence: Any,
    review_status: str | None = None,
) -> DocumentStatus:
    """Map lease status + extraction confidence onto an explorer pill.

    Args:
        upload_status: Raw lease status (pending/staged/processing/completed/failed).
        extraction_confidence: Pipeline extraction confidence, when an artifact
            row exists; ``None`` when the artifact is missing.
        review_status: Persisted human review lifecycle, when present.

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
    if review_status == "pending":
        return DocumentStatus.REVIEW_NEEDED
    if review_status == "committed":
        return DocumentStatus.EXTRACTED
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
    """Explorer detail with parsed extraction and structured data."""

    classification: dict[str, Any] | None = None
    artifact: dict[str, Any] | None = None
    review: dict[str, Any] | None = None
    structured_data: dict[str, Any] | None = None


class ContractTermReviewInput(BaseModel):
    """One editable commercial pricing term submitted for human commitment."""

    product_code: str | None = Field(default=None, max_length=128)
    description: str | None = None
    unit_price: Decimal = Field(ge=0)
    currency: str = Field(default="USD", min_length=3, max_length=3)
    uom: str | None = Field(default=None, max_length=32)
    qty_min: Decimal | None = Field(default=None, ge=0)
    qty_max: Decimal | None = Field(default=None, ge=0)
    discount_pct: Decimal | None = Field(default=None, ge=0, le=100)
    effective_from: date
    effective_to: date | None = None
    escalation_pct: Decimal | None = Field(default=None, ge=0, le=100)
    payment_terms: str | None = None
    freight_terms: str | None = None
    tax_rule: str | None = None

    @model_validator(mode="after")
    def validate_effective_dates(self) -> "ContractTermReviewInput":
        """Reject an expiration date earlier than the term's effective date."""
        if self.effective_to is not None and self.effective_to < self.effective_from:
            raise ValueError("effective_to must be on or after effective_from")
        return self

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str) -> str:
        """Normalize ISO currency codes to uppercase."""
        return value.upper()


class ContractReviewCommitRequest(BaseModel):
    """Human-corrected contract header and terms ready for the ledger."""

    contract_number: str = Field(min_length=1, max_length=128)
    vendor_name: str = Field(min_length=1, max_length=256)
    title: str | None = Field(default=None, max_length=256)
    start_date: date
    end_date: date | None = None
    renewal_date: date | None = None
    notice_period_days: int | None = Field(default=None, ge=0, le=3650)
    auto_renew: bool = False
    termination_clause: str | None = None
    terms: list[ContractTermReviewInput] = Field(min_length=1)

    @field_validator("contract_number", "vendor_name")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        """Disallow whitespace-only required contract identifiers."""
        normalized = value.strip()
        if not normalized:
            raise ValueError("This field cannot be blank")
        return normalized

    @model_validator(mode="after")
    def validate_contract_dates(self) -> "ContractReviewCommitRequest":
        """Ensure header date fields are chronologically plausible."""
        if self.end_date is not None and self.end_date < self.start_date:
            raise ValueError("end_date must be on or after start_date")
        if self.renewal_date is not None and self.renewal_date < self.start_date:
            raise ValueError("renewal_date must be on or after start_date")
        return self


class ContractReviewCommitResponse(BaseModel):
    """Result of promoting verified commercial terms to the ledger."""

    document_id: UUID
    contract_id: UUID
    term_version_ids: list[UUID]
    review_status: str
    reviewed_at: datetime


class DocumentFileResponse(BaseModel):
    """Short-lived signed GET URL for inline preview + download."""

    document_id: UUID
    url: str
    expires_at: datetime
