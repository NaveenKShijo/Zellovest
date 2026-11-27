"""RAG schemas."""

from datetime import date
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


class DocumentSearchRequest(BaseModel):
    """Request to search documents."""

    tenant_id: str | None = Field(default=None, min_length=1, max_length=128)
    query: str = Field(..., min_length=1, max_length=500)
    vendor_id: UUID | None = None
    document_id: UUID | None = None
    document_type: str | None = Field(
        default=None,
        pattern=r"^(contract|amendment|invoice|purchase_order|po|policy|other)$",
    )
    date_from: date | None = Field(default=None, description="Inclusive UTC date added")
    date_to: date | None = Field(default=None, description="Inclusive UTC date added")
    limit: int = Field(default=10, ge=1, le=50)

    @model_validator(mode="after")
    def validate_date_range(self) -> "DocumentSearchRequest":
        """Reject inverted date-added ranges."""
        if self.date_from and self.date_to and self.date_from > self.date_to:
            raise ValueError("date_from must be on or before date_to")
        return self


class DocumentChunk(BaseModel):
    """Document chunk with provenance."""

    chunk_id: str
    document_id: str
    document_type: str
    vendor_id: str | None
    page: int | None
    section: str | None
    content: str
    score: float
    provenance: dict[str, Any] | None = None


class DocumentSearchResponse(BaseModel):
    """Document search results."""

    query: str
    chunks: list[DocumentChunk]
    total_results: int
    search_time_ms: int


class DocumentUploadRequest(BaseModel):
    """Request to upload a document for RAG."""

    tenant_id: str | None = Field(default=None, min_length=1, max_length=128)
    vendor_id: str | None = None
    document_type: str = Field(
        ..., pattern=r"^(contract|amendment|invoice|purchase_order|po|policy|other)$"
    )
    title: str = Field(..., min_length=1, max_length=256)
    content: str  # Base64 encoded or text
    metadata: dict[str, Any] | None = None


class DocumentUploadResponse(BaseModel):
    """Document upload response."""

    document_id: UUID
    chunks_created: int
    status: str
    message: str


class RAGEvaluationRequest(BaseModel):
    """Request an LLM-judge evaluation using already indexed contract passages."""

    tenant_id: str | None = Field(default=None, min_length=1, max_length=128)
    sample_size: int = Field(default=5, ge=1, le=5)
    questions_per_passage: int = Field(default=2, ge=1, le=2)
    vendor_id: str | None = None


class RAGEvaluationResult(BaseModel):
    """Evaluation scores and run metadata; contains no prompts or source text."""

    run_id: UUID
    evaluator_model: str
    evaluated_questions: int
    mean_relevance: float
    mean_faithfulness: float
    mean_citation_support: float
    mean_context_coverage: float
    results: list[dict[str, Any]]
