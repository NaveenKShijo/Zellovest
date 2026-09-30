"""RAG schemas."""

from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class DocumentSearchRequest(BaseModel):
    """Request to search documents."""

    tenant_id: str = Field(..., min_length=1, max_length=128)
    query: str = Field(..., min_length=1, max_length=500)
    vendor_id: str | None = None
    document_type: str | None = None  # contract, invoice, po, policy, etc.
    date_from: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    date_to: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    limit: int = Field(default=10, ge=1, le=50)


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

    tenant_id: str = Field(..., min_length=1, max_length=128)
    vendor_id: str | None = None
    document_type: str = Field(..., pattern="^(contract|invoice|po|policy|other)$")
    title: str = Field(..., min_length=1, max_length=256)
    content: str  # Base64 encoded or text
    metadata: dict[str, Any] | None = None


class DocumentUploadResponse(BaseModel):
    """Document upload response."""

    document_id: UUID
    chunks_created: int
    status: str
    message: str