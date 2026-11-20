"""Bounded tool execution with risk gating.

The executor is where PRD 24-25 become concrete:

* read-only tools run immediately;
* low-risk writes run inline only when the user allowed actions, always with an
  idempotency key;
* high-risk writes are never executed automatically - they become
  ``ProposedAction`` records, with a dry-run preview when the tool supports it;
* any transport/tool failure becomes an explicit ``DataGap`` so synthesis can
  say "unavailable" instead of inferring "zero".
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

from zellovest_shared.logging_conf import get_logger
from zellovest_shared.mcp_contracts import ToolContract

from zellovest_agentic.agent.planner import Plan, PlanStep
from zellovest_agentic.mcp.client import McpHostError, McpIdentity, McpToolResult
from zellovest_agentic.mcp.pool import McpPool
from zellovest_agentic.schemas.ask_ai import (
    DataGap,
    EvidenceItem,
    ProposedAction,
    ToolCall,
)

logger = get_logger(__name__)

_DOCUMENT_SEARCH_TOOLS = frozenset(
    {
        "search_documents",
        "search_contracts",
        "search_invoices",
        "search_vendor_policies",
        "search_document_chunks",
    }
)

_MAX_EVIDENCE_PER_CALL = 8
_MAX_EXCERPT_CHARS = 1200


@dataclass
class ToolOutcome:
    """Internal record of one tool attempt (success or controlled failure)."""

    tool: str
    server: str
    risk_class: str
    operation: str
    purpose: str
    success: bool
    data: dict[str, Any] | None = None
    error_code: str | None = None
    error_message: str | None = None
    retryable: bool = False
    latency_ms: int = 0
    attempts: int = 1
    idempotency_key: str | None = None


@dataclass
class ExecutionResult:
    """Everything gathered for synthesis and for the API response."""

    outcomes: list[ToolOutcome] = field(default_factory=list)
    evidence: list[EvidenceItem] = field(default_factory=list)
    data_gaps: list[DataGap] = field(default_factory=list)
    proposed_actions: list[ProposedAction] = field(default_factory=list)
    tool_calls: list[ToolCall] = field(default_factory=list)


def _action_id(tool: str, arguments: dict[str, Any]) -> str:
    """Return a stable identifier for a proposed action."""
    payload = json.dumps(
        {"tool": tool, "arguments": arguments},
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _excerpt(value: Any, limit: int = _MAX_EXCERPT_CHARS) -> str | None:
    """Serialize a tool value to a bounded, display-safe excerpt."""
    if value is None:
        return None
    if isinstance(value, str):
        text = value
    else:
        text = json.dumps(value, default=str, ensure_ascii=False)
    text = text.strip()
    return text[:limit] if text else None


def _document_evidence(
    tool: str,
    server: str,
    data: dict[str, Any],
    start_index: int,
) -> list[EvidenceItem]:
    """Convert document chunks into citation-ready evidence items."""
    items: list[EvidenceItem] = []
    chunks = data.get("chunks")
    if not isinstance(chunks, list):
        return items
    for offset, chunk in enumerate(chunks[:_MAX_EVIDENCE_PER_CALL]):
        if not isinstance(chunk, dict):
            continue
        filename = chunk.get("filename") or "Document"
        page = chunk.get("page")
        section = chunk.get("section")
        title = str(chunk.get("citation") or filename)
        items.append(
            EvidenceItem(
                evidence_id=f"ev-{start_index + offset}",
                kind="document",
                title=title,
                tool=tool,
                server=server,
                document_id=str(chunk.get("document_id") or "") or None,
                chunk_id=str(chunk.get("chunk_id") or "") or None,
                page=int(page) if isinstance(page, int) else None,
                section=str(section) if section else None,
                bbox=chunk.get("bbox") if isinstance(chunk.get("bbox"), list) else None,
                excerpt=_excerpt(chunk.get("content") or chunk.get("parent_content"), 1500),
                as_of=str(chunk.get("as_of") or "") or None,
            )
        )
    return items


def _structured_evidence(
    tool: str,
    server: str,
    data: dict[str, Any],
    start_index: int,
) -> EvidenceItem:
    """Create one evidence item for a structured/analytic tool result."""
    kind = "calculation" if tool.startswith("calculate_") else "structured"
    if server == "mcp-3-external":
        kind = "external"
    summary = str(data.get("summary") or "").strip() or f"{tool} result"
    return EvidenceItem(
        evidence_id=f"ev-{start_index}",
        kind=kind,  # type: ignore[arg-type]
        title=summary[:256],
        tool=tool,
        server=server,
        source_id=str(
            data.get("vendor_id")
            or data.get("contract_id")
            or data.get("invoice_id")
            or data.get("document_id")
            or ""
        )
        or None,
        excerpt=_excerpt(data),
        as_of=str(data.get("as_of") or "") or None,
    )


class PlanExecutor:
    """Execute a plan against the MCP pool with risk gating and idempotency."""

    def __init__(self, pool: McpPool) -> None:
        """Store the MCP pool and its transport configuration."""
        self.pool = pool

    async def execute(
        self,
        plan: Plan,
        identity: McpIdentity,
        *,
        auto_execute_actions: bool,
        preview_high_risk: bool = True,
    ) -> ExecutionResult:
        """Run every permitted step and classify each result.

        Args:
            plan: Validated plan.
            identity: Authenticated caller context.
            auto_execute_actions: When True, low-risk writes requested by the
                user run inline; when False every write is only proposed.
            preview_high_risk: Fetch a dry-run preview for high-risk proposals.

        Returns:
            ExecutionResult with evidence, gaps, proposals, and tool traces.
        """
        result = ExecutionResult()
        registry = self.pool.registry_for(identity.role)
        evidence_index = 0

        for step in plan.steps:
            contract = registry.get(step.tool)
            if contract is None:  # pragma: no cover - planner guarantees visibility
                continue
            if contract.operation == "write" and (
                contract.requires_confirmation or not auto_execute_actions
            ):
                proposal = await self._propose(
                    contract,
                    step,
                    identity,
                    preview=contract.requires_confirmation and preview_high_risk,
                )
                result.proposed_actions.append(proposal)
                result.tool_calls.append(
                    ToolCall(
                        tool=step.tool,
                        server=contract.server,
                        risk_class=contract.risk_class,
                        arguments=step.arguments,
                        success=proposal.executed,
                        error=proposal.error,
                        purpose=step.purpose,
                    )
                )
                continue

            outcome = await self._call(contract, step, identity, execute_write=True)
            result.outcomes.append(outcome)
            result.tool_calls.append(
                ToolCall(
                    tool=step.tool,
                    server=contract.server,
                    risk_class=contract.risk_class,
                    arguments=step.arguments,
                    result=None,
                    error=outcome.error_message if not outcome.success else None,
                    success=outcome.success,
                    latency_ms=outcome.latency_ms,
                    attempts=outcome.attempts,
                    purpose=step.purpose,
                )
            )
            if not outcome.success:
                result.data_gaps.append(
                    DataGap(
                        tool=step.tool,
                        server=contract.server,
                        code=outcome.error_code or "unavailable",
                        message=outcome.error_message or "tool unavailable",
                        retryable=outcome.retryable,
                    )
                )
                continue

            data = outcome.data or {}
            if step.tool in _DOCUMENT_SEARCH_TOOLS:
                items = _document_evidence(step.tool, contract.server, data, evidence_index)
                if not items and int(data.get("count") or 0) == 0:
                    result.data_gaps.append(
                        DataGap(
                            tool=step.tool,
                            server=contract.server,
                            code="no_matches",
                            message="no indexed passages matched this query",
                        )
                    )
            else:
                items = [
                    _structured_evidence(step.tool, contract.server, data, evidence_index)
                ]
            result.evidence.extend(items)
            evidence_index += len(items)

            if contract.operation == "write":
                result.proposed_actions.append(
                    ProposedAction(
                        action_id=_action_id(step.tool, step.arguments),
                        tool=step.tool,
                        server=contract.server,
                        risk_class=contract.risk_class,
                        description=step.purpose or contract.description,
                        arguments=step.arguments,
                        idempotency_key=str(outcome.idempotency_key or ""),
                        requires_confirmation=False,
                        dry_run_by_default=False,
                        executed=True,
                        result=data,
                    )
                )

        return result

    async def _call(
        self,
        contract: ToolContract,
        step: PlanStep,
        identity: McpIdentity,
        *,
        execute_write: bool,
    ) -> ToolOutcome:
        """Invoke one tool, translating controlled failures into outcomes."""
        arguments = dict(step.arguments)
        idempotency_key: str | None = None
        if contract.operation == "write":
            idempotency_key = self.pool.derive_idempotency_key(
                step.tool, arguments, identity
            )
            arguments["idempotency_key"] = idempotency_key
            if execute_write:
                arguments["dry_run"] = False
        try:
            tool_result: McpToolResult = await self.pool.call_tool(
                step.tool,
                arguments,
                identity,
                purpose=step.purpose,
                idempotency_key=idempotency_key,
            )
        except McpHostError as exc:
            return ToolOutcome(
                tool=step.tool,
                server=contract.server,
                risk_class=contract.risk_class,
                operation=contract.operation,
                purpose=step.purpose,
                success=False,
                error_code=exc.code,
                error_message=exc.message,
                retryable=exc.retryable,
            )
        outcome = ToolOutcome(
            tool=step.tool,
            server=contract.server,
            risk_class=contract.risk_class,
            operation=contract.operation,
            purpose=step.purpose,
            success=True,
            data=tool_result.data,
            latency_ms=tool_result.latency_ms,
            attempts=tool_result.attempts,
            idempotency_key=idempotency_key,
        )
        return outcome

    async def _propose(
        self,
        contract: ToolContract,
        step: PlanStep,
        identity: McpIdentity,
        *,
        preview: bool,
    ) -> ProposedAction:
        """Build a proposed action and, for high risk, a dry-run preview."""
        arguments = dict(step.arguments)
        idempotency_key = self.pool.derive_idempotency_key(
            step.tool, arguments, identity
        )
        arguments["idempotency_key"] = idempotency_key
        preview_payload: dict[str, Any] | None = None
        error: str | None = None
        if preview:
            try:
                preview_result = await self.pool.call_tool(
                    step.tool,
                    {**arguments, "dry_run": True},
                    identity,
                    purpose="dry-run preview before human confirmation",
                    idempotency_key=idempotency_key,
                )
                preview_payload = preview_result.data
            except McpHostError as exc:
                error = exc.message
                logger.warning(
                    "mcp_action_preview_failed",
                    tool=step.tool,
                    server=contract.server,
                    error_code=exc.code,
                    correlation_id=identity.correlation_id,
                )
        return ProposedAction(
            action_id=_action_id(step.tool, arguments),
            tool=step.tool,
            server=contract.server,
            risk_class=contract.risk_class,
            description=step.purpose or contract.description,
            arguments=arguments,
            idempotency_key=idempotency_key,
            requires_confirmation=contract.requires_confirmation,
            dry_run_by_default=True,
            executed=False,
            preview=preview_payload,
            error=error,
        )


__all__ = ["ExecutionResult", "PlanExecutor", "ToolOutcome"]
