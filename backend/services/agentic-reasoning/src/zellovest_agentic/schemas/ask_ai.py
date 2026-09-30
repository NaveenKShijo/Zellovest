"""Ask AI schemas."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class AskAIRequest(BaseModel):
    """Request to Ask AI."""

    tenant_id: str = Field(..., min_length=1, max_length=128)
    question: str = Field(..., min_length=1, max_length=2000)
    context: dict[str, Any] | None = None
    conversation_id: UUID | None = None
    stream: bool = Field(default=True)


class ToolCall(BaseModel):
    """Tool call made by the agent."""

    tool: str
    arguments: dict[str, Any]
    result: dict[str, Any] | None = None
    error: str | None = None


class Citation(BaseModel):
    """Citation for evidence."""

    source_type: str  # "document", "database", "calculation"
    source_id: str
    description: str
    excerpt: str | None = None


class AskAIResponse(BaseModel):
    """Response from Ask AI."""

    answer: str
    conversation_id: UUID
    citations: list[Citation] = []
    tool_calls: list[ToolCall] = []
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    generated_at: datetime
    processing_time_ms: int


class ConversationHistory(BaseModel):
    """Conversation history entry."""

    conversation_id: UUID
    question: str
    answer: str
    created_at: datetime


class ConversationListResponse(BaseModel):
    """Paginated conversation list."""

    conversations: list[ConversationHistory]
    total: int
    page: int
    page_size: int