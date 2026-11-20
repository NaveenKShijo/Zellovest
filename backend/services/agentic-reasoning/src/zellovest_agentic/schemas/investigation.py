"""Response schemas for evidence-first procurement investigations."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class InvestigationCitation(BaseModel):
    """A structured source reference supporting an investigation finding."""

    tool: str
    source_id: str | None = None
    document_id: str | None = None
    page: int | None = None
    section: str | None = None
    excerpt: str | None = None


class InvestigationFinding(BaseModel):
    """One fact, deterministic calculation, hypothesis, or review item."""

    statement: str
    citations: list[InvestigationCitation] = Field(default_factory=list)


class InvestigationDataGap(BaseModel):
    """A failed or unavailable source that must not be treated as zero."""

    tool: str
    code: str
    message: str


class InvestigationToolTrace(BaseModel):
    """Safe trace of a bounded MCP call used by the investigation."""

    tool: str
    success: bool
    result_summary: str | None = None


class ReconciliationInvestigationResponse(BaseModel):
    """Evidence-led explanation of one reconciliation exception."""

    exception_id: str
    summary: str
    confirmed_facts: list[InvestigationFinding] = Field(default_factory=list)
    calculated_values: list[InvestigationFinding] = Field(default_factory=list)
    possible_explanations: list[InvestigationFinding] = Field(default_factory=list)
    needs_human_review: list[InvestigationFinding] = Field(default_factory=list)
    citations: list[InvestigationCitation] = Field(default_factory=list)
    data_gaps: list[InvestigationDataGap] = Field(default_factory=list)
    tool_trace: list[InvestigationToolTrace] = Field(default_factory=list)
    generated_at: datetime
