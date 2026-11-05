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
    contract_line_id: UUID | None = None
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
    reviewer_notes: str | None = None
    parent_contract_id: UUID | None = None
    change_type: str | None = Field(default=None, pattern="^(original|amendment|renewal|price_revision)$")
    removed_contract_line_ids: list[UUID] = Field(default_factory=list)
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
    contract_version_id: UUID
    version_no: int
    term_version_ids: list[UUID]
    review_status: str
    reviewed_at: datetime


class ContractCandidateTerm(BaseModel):
    """Current contract line offered while resolving an amendment parent."""

    contract_line_id: UUID
    product_code: str | None
    description: str | None
    unit_price: Decimal
    currency: str
    uom: str | None
    qty_min: Decimal | None
    qty_max: Decimal | None
    effective_from: date
    effective_to: date | None


class ContractCandidate(BaseModel):
    """An existing contract that a reviewer may select as the amendment parent."""

    contract_id: UUID
    contract_number: str
    title: str | None
    vendor_name: str
    latest_version_no: int | None
    terms: list[ContractCandidateTerm]


class ContractCandidatesResponse(BaseModel):
    """Tenant-scoped contract matches for a staged amendment."""

    document_id: UUID
    candidates: list[ContractCandidate]


class ContractHistoryTerm(BaseModel):
    """One product or pricing tier inside a contract version event."""

    id: UUID
    contract_line_id: UUID
    line_no: int
    product_code: str | None
    description: str | None
    unit_price: Decimal
    currency: str
    uom: str | None
    qty_min: Decimal | None
    qty_max: Decimal | None
    discount_pct: Decimal | None
    tax_rule: str | None
    payment_terms: str | None
    freight_terms: str | None
    effective_from: date
    effective_to: date | None


class ContractHistoryVersion(BaseModel):
    """One version event with source and parent document lineage."""

    id: UUID
    version_no: int
    change_type: str
    source_document_id: UUID | None
    source_filename: str | None
    source_upload_id: UUID | None
    parent_version_id: UUID | None
    parent_version_no: int | None
    effective_from: date
    effective_to: date | None
    terms: list[ContractHistoryTerm]


class ContractHistoryResponse(BaseModel):
    """Contract header and chronological source-backed version history."""

    contract_id: UUID
    vendor_id: UUID
    vendor_name: str
    contract_number: str
    title: str | None
    versions: list[ContractHistoryVersion]


class InvoiceLineReviewInput(BaseModel):
    """One human-corrected invoice line item."""

    description: str = ""
    product_code: str | None = Field(default=None, max_length=128)
    quantity: Decimal = Field(gt=0)
    unit_price: Decimal = Field(ge=0)
    total: Decimal | None = Field(default=None, ge=0)


class InvoiceReviewCommitRequest(BaseModel):
    """Human-corrected invoice header and lines ready for the ledger."""

    invoice_number: str = Field(min_length=1, max_length=128)
    vendor_name: str = Field(min_length=1, max_length=256)
    invoice_date: date
    due_date: date | None = None
    currency: str = Field(default="USD", min_length=3, max_length=3)
    subtotal: Decimal = Field(ge=0)
    tax_amount: Decimal = Field(default=Decimal("0"), ge=0)
    total_amount: Decimal = Field(ge=0)
    reviewer_notes: str | None = None
    line_items: list[InvoiceLineReviewInput] = Field(min_length=1)

    @field_validator("invoice_number", "vendor_name")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        """Disallow whitespace-only required invoice identifiers."""
        normalized = value.strip()
        if not normalized:
            raise ValueError("This field cannot be blank")
        return normalized

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str) -> str:
        """Normalize ISO currency codes to uppercase."""
        return value.upper()

    @model_validator(mode="after")
    def validate_invoice_dates(self) -> "InvoiceReviewCommitRequest":
        """Reject a due date earlier than the invoice date."""
        if self.due_date is not None and self.due_date < self.invoice_date:
            raise ValueError("due_date must be on or after invoice_date")
        return self


class InvoiceReviewCommitResponse(BaseModel):
    """Result of promoting verified invoice fields to the ledger."""

    document_id: UUID
    invoice_id: UUID
    review_status: str
    reviewed_at: datetime


class DocumentFileResponse(BaseModel):
    """Short-lived signed GET URL for inline preview + download."""

    document_id: UUID
    url: str
    expires_at: datetime
