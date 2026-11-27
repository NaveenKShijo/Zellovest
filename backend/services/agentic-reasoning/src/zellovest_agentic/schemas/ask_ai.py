"""Ask AI schemas: Answer + Evidence + Proposed Actions (PRD 22-25)."""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field


class AskAIRequest(BaseModel):
    """Request to Ask AI."""

    tenant_id: str | None = Field(default=None, min_length=1, max_length=128)
    question: str = Field(..., min_length=1, max_length=2000)
    context: dict[str, Any] | None = None
    conversation_id: UUID | None = None
    stream: bool = Field(default=True)
    # Low-risk actions explicitly requested by the user may run inline
    # (MODULES M8). High-risk actions are never executed from this flag.
    auto_execute_actions: bool = Field(default=True)


class ToolCall(BaseModel):
    """One tool invocation made while answering."""

    tool: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    result: dict[str, Any] | None = None
    error: str | None = None
    server: str | None = None
    risk_class: str | None = None
    success: bool = True
    latency_ms: int = 0
    attempts: int = 1
    purpose: str | None = None


class Citation(BaseModel):
    """Citation for evidence (frontend-compatible shape)."""

    source_type: str  # "document", "database", "calculation"
    source_id: str
    description: str
    excerpt: str | None = None
    evidence_id: str | None = None
    page: int | None = None
    bbox: list[float] | None = None


class EvidenceItem(BaseModel):
    """One piece of evidence backing the answer."""

    evidence_id: str
    kind: Literal["document", "structured", "calculation", "external", "action"]
    title: str
    tool: str
    server: str
    source_id: str | None = None
    document_id: str | None = None
    chunk_id: str | None = None
    page: int | None = None
    section: str | None = None
    bbox: list[float] | None = None
    excerpt: str | None = None
    source_context: str | None = Field(default=None, exclude=True, repr=False)
    source_parent_id: str | None = Field(default=None, exclude=True, repr=False)
    as_of: str | None = None
    unavailable: bool = False


class DataGap(BaseModel):
    """An explicitly unavailable fact, distinct from a confirmed zero."""

    tool: str | None = None
    server: str | None = None
    code: str = "unavailable"
    message: str
    retryable: bool = False


class AnswerSections(BaseModel):
    """Separates confirmed facts, calculations, hypotheses, and review items."""

    facts: list[str] = Field(default_factory=list)
    calculations: list[str] = Field(default_factory=list)
    hypotheses: list[str] = Field(default_factory=list)
    needs_review: list[str] = Field(default_factory=list)


class ProposedAction(BaseModel):
    """A tool action shown to the user, optionally executed or held for confirmation."""

    action_id: str
    tool: str
    server: str
    risk_class: str
    description: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str
    requires_confirmation: bool = False
    dry_run_by_default: bool = True
    executed: bool = False
    result: dict[str, Any] | None = None
    preview: dict[str, Any] | None = None
    error: str | None = None


class AskAIResponse(BaseModel):
    """Answer + Evidence + Proposed Actions."""

    answer: str
    conversation_id: UUID
    citations: list[Citation] = Field(default_factory=list)
    tool_calls: list[ToolCall] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    generated_at: datetime
    processing_time_ms: int
    evidence: list[EvidenceItem] = Field(default_factory=list)
    proposed_actions: list[ProposedAction] = Field(default_factory=list)
    data_gaps: list[DataGap] = Field(default_factory=list)
    sections: AnswerSections = Field(default_factory=AnswerSections)
    intent: str | None = None
    plan_source: str | None = None
    trace_id: str | None = None


class ConversationMessage(BaseModel):
    """One persisted message in a conversation."""

    message_id: UUID
    role: str
    content: str
    created_at: datetime
    citations: list[Citation] = Field(default_factory=list)
    evidence: list[EvidenceItem] = Field(default_factory=list)
    proposed_actions: list[ProposedAction] = Field(default_factory=list)
    data_gaps: list[DataGap] = Field(default_factory=list)
    tool_calls: list[ToolCall] = Field(default_factory=list)
    sections: AnswerSections | None = None
    intent: str | None = None


class ConversationHistory(BaseModel):
    """Conversation summary (list) or detail (single)."""

    conversation_id: UUID
    question: str = ""
    answer: str = ""
    created_at: datetime
    title: str = ""
    message_count: int = 0
    last_message_at: datetime | None = None
    messages: list[ConversationMessage] = Field(default_factory=list)


class ConversationListResponse(BaseModel):
    """Paginated conversation list."""

    conversations: list[ConversationHistory]
    total: int
    page: int
    page_size: int


class ActionPreviewRequest(BaseModel):
    """Request a dry-run preview of a proposed action."""

    tool_name: str = Field(..., min_length=1)
    arguments: dict[str, Any] = Field(default_factory=dict)


class ActionPreviewResponse(BaseModel):
    """Dry-run preview; nothing is persisted or sent."""

    tool: str
    server: str
    risk_class: str
    requires_confirmation: bool
    arguments: dict[str, Any]
    preview: dict[str, Any]


class ActionConfirmRequest(BaseModel):
    """Explicit human confirmation of one high-risk action."""

    tool_name: str = Field(..., min_length=1)
    arguments: dict[str, Any]
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=128)
    conversation_id: UUID | None = None
    confirmation_note: str | None = Field(default=None, max_length=1000)


class ActionConfirmResponse(BaseModel):
    """Result of a confirmed action."""

    tool: str
    server: str
    risk_class: str
    success: bool
    result: dict[str, Any] | None = None
    error: str | None = None
    expires_at: datetime | None = None
    conversation_id: UUID | None = None
