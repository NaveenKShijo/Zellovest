"""Unit tests for the Ask AI agent pipeline and MCP risk gating.

These tests stub the MCP transport, so they verify host behavior (planning
validation, evidence extraction, idempotency, risk classification, and
no-fabrication fallbacks) without requiring live MCP processes. The live
transport is covered by the MCP smoke tests.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import uuid
from typing import Any

import pytest
from zellovest_agentic.agent.agent import ActionService, AskAIAgent
from zellovest_agentic.agent.executor import ExecutionResult, PlanExecutor
from zellovest_agentic.agent.planner import AgentPlanner, Plan, PlanStep
from zellovest_agentic.agent.synthesizer import AnswerSynthesizer
from zellovest_agentic.mcp import McpHostError, McpIdentity, McpToolResult
from zellovest_agentic.mcp.registry import ToolRegistry
from zellovest_agentic.schemas.ask_ai import DataGap, EvidenceItem
from zellovest_shared.mcp_contracts import TOOL_CONTRACTS

TENANT = "tenant-test"
IDENTITY = McpIdentity(
    tenant_id=TENANT,
    actor_id="user-test",
    role="procurement_member",
    correlation_id="corr-test",
    deployment_id=TENANT,
)


@dataclass
class FakeSettings:
    """Minimal settings object used by the agent stages under test."""

    agent_max_plan_steps: int = 6
    agent_history_turns: int = 6
    agent_evidence_chars: int = 4000
    agent_conversation_persistence: bool = False
    ask_ai_confirmation_ttl_seconds: int = 900
    mcp_service_token: str = "test-service-token"
    mcp_confirmation_secret: str = "test-confirmation-secret"


class FakePool:
    """MCP pool double that records calls and returns canned data."""

    def __init__(
        self,
        data: dict[str, Any] | None = None,
        error: McpHostError | None = None,
    ) -> None:
        self.data = data or {}
        self.error = error
        self.calls: list[dict[str, Any]] = []

    def registry_for(self, role: str) -> ToolRegistry:
        """Return the real role-filtered catalog."""
        return ToolRegistry(role)

    def derive_idempotency_key(
        self, tool_name: str, arguments: dict[str, Any], identity: McpIdentity
    ) -> str:
        """Return a stable fake idempotency key."""
        return f"idem-{tool_name}-{identity.tenant_id}"

    async def call_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        identity: McpIdentity,
        *,
        purpose: str | None = None,
        idempotency_key: str | None = None,
    ) -> McpToolResult:
        """Record the call and return canned data or raise the configured error."""
        self.calls.append(
            {
                "tool": tool_name,
                "arguments": dict(arguments),
                "identity": identity,
                "purpose": purpose,
                "idempotency_key": idempotency_key,
            }
        )
        if self.error is not None:
            raise self.error
        contract = TOOL_CONTRACTS[tool_name]
        return McpToolResult(
            server=contract.server,
            tool=tool_name,
            tool_version=contract.version,
            risk_class=contract.risk_class,
            operation=contract.operation,
            data=self.data,
            latency_ms=5,
            attempts=1,
            correlation_id=identity.correlation_id,
            arguments_digest="test-digest",
            result_size=len(str(self.data)),
        )


class FakeStore:
    """Conversation store double that never touches PostgreSQL."""

    def __init__(self) -> None:
        self.conversation_id = uuid.uuid4()
        self.assistant_payloads: list[dict[str, Any]] = []

    async def resolve(self, **_: Any) -> uuid.UUID:
        """Return a stable conversation id."""
        return self.conversation_id

    async def history(self, **_: Any) -> list[dict[str, str]]:
        """Return no prior turns."""
        return []

    async def append_user(self, **_: Any) -> None:
        """Ignore user messages."""

    async def append_assistant(self, **kwargs: Any) -> None:
        """Record the structured assistant payload."""
        self.assistant_payloads.append(kwargs.get("payload") or {})


def test_heuristic_plan_uses_only_read_tools() -> None:
    """Deterministic planning never proposes a write action."""
    registry = ToolRegistry("procurement_member")
    plan = AgentPlanner(enabled=False).plan(
        question="Create a reminder to cancel the Adobe contract next month",
        context={},
        history=[],
        registry=registry,
    )
    assert plan.source == "heuristic"
    assert all(
        TOOL_CONTRACTS[step.tool].operation == "read" for step in plan.steps
    )


@pytest.mark.asyncio
async def test_executor_read_tool_builds_structured_evidence() -> None:
    pool = FakePool(
        data={
            "count": 1,
            "as_of": "2026-11-22",
            "renewals": [{"contract_id": "c-1", "vendor_name": "Adobe"}],
        }
    )
    plan = Plan(
        intent="renewal_review",
        steps=(PlanStep(tool="find_renewals", arguments={"days_ahead": 90}),),
    )
    result = await PlanExecutor(pool).execute(plan, IDENTITY, auto_execute_actions=True)

    assert len(result.evidence) == 1
    assert result.evidence[0].kind == "structured"
    assert result.evidence[0].tool == "find_renewals"
    assert result.tool_calls[0].success is True
    assert result.data_gaps == []
    assert result.proposed_actions == []


@pytest.mark.asyncio
async def test_executor_high_risk_write_is_only_previewed() -> None:
    """A high-risk write is proposed with a dry-run preview, never executed."""
    pool = FakePool(data={"status": "dry_run", "dry_run": True, "summary": "preview"})
    plan = Plan(
        intent="send_follow_up",
        steps=(
            PlanStep(
                tool="send_email",
                arguments={
                    "to": ["vendor@example.com"],
                    "subject": "Renewal",
                    "body": "Checking in",
                },
            ),
        ),
    )
    result = await PlanExecutor(pool).execute(plan, IDENTITY, auto_execute_actions=True)

    assert len(result.proposed_actions) == 1
    action = result.proposed_actions[0]
    assert action.tool == "send_email"
    assert action.requires_confirmation is True
    assert action.executed is False
    assert action.preview == {"status": "dry_run", "dry_run": True, "summary": "preview"}
    assert result.evidence == []
    assert len(pool.calls) == 1
    assert pool.calls[0]["arguments"]["dry_run"] is True
    assert pool.calls[0]["arguments"]["idempotency_key"]


@pytest.mark.asyncio
async def test_executor_low_risk_write_executes_with_idempotency() -> None:
    """A low-risk write requested by the user runs inline with a derived key."""
    pool = FakePool(data={"status": "created", "workflow_id": "w-1"})
    plan = Plan(
        intent="create_task",
        steps=(
            PlanStep(
                tool="create_procurement_task",
                arguments={"title": "Review Adobe renewal"},
            ),
        ),
    )
    result = await PlanExecutor(pool).execute(plan, IDENTITY, auto_execute_actions=True)

    assert len(result.proposed_actions) == 1
    action = result.proposed_actions[0]
    assert action.executed is True
    assert action.requires_confirmation is False
    assert action.idempotency_key
    assert pool.calls[0]["arguments"]["dry_run"] is False
    assert pool.calls[0]["arguments"]["idempotency_key"] == action.idempotency_key


@pytest.mark.asyncio
async def test_executor_does_not_execute_low_risk_when_actions_disabled() -> None:
    """When the user disables actions, even low-risk writes are only proposed."""
    pool = FakePool(data={"status": "created"})
    plan = Plan(
        intent="create_task",
        steps=(
            PlanStep(
                tool="create_procurement_task",
                arguments={"title": "Review Adobe renewal"},
            ),
        ),
    )
    result = await PlanExecutor(pool).execute(plan, IDENTITY, auto_execute_actions=False)

    assert result.proposed_actions[0].executed is False
    assert pool.calls == []


@pytest.mark.asyncio
async def test_executor_tool_failure_becomes_data_gap() -> None:
    """An unavailable tool is reported as unavailable, not as zero."""
    pool = FakePool(
        error=McpHostError(
            "unavailable",
            "MCP-1 is unreachable",
            server="mcp-1-procurement",
            tool="find_renewals",
            retryable=True,
        )
    )
    plan = Plan(
        intent="renewal_review",
        steps=(PlanStep(tool="find_renewals", arguments={"days_ahead": 90}),),
    )
    result = await PlanExecutor(pool).execute(plan, IDENTITY, auto_execute_actions=True)

    assert result.evidence == []
    assert len(result.data_gaps) == 1
    gap = result.data_gaps[0]
    assert gap.code == "unavailable"
    assert gap.tool == "find_renewals"
    assert result.tool_calls[0].success is False


def test_deterministic_synthesis_marks_unavailable_data() -> None:
    """Without evidence, synthesis says unavailable instead of inferring zero."""
    synthesizer = AnswerSynthesizer(FakeSettings(), enabled=False)
    execution = ExecutionResult(
        data_gaps=[
            DataGap(
                tool="find_renewals",
                server="mcp-1-procurement",
                message="tool unavailable",
            )
        ]
    )
    result = synthesizer.synthesize(
        question="What renews next quarter?",
        plan=Plan(intent="renewal_review"),
        execution=execution,
    )

    assert result.source == "deterministic"
    assert "Unavailable data" in result.answer
    assert "not zero" in result.answer
    assert result.citations == []
    assert result.confidence <= 0.2


def test_synthesis_drops_citations_not_in_evidence() -> None:
    """The model cannot cite an evidence id that was not retrieved."""
    synthesizer = AnswerSynthesizer(FakeSettings())
    evidence = EvidenceItem(
        evidence_id="ev-1",
        kind="document",
        title="Adobe Agreement page 4",
        tool="search_contracts",
        server="mcp-2-documents",
        document_id="doc-1",
        page=4,
        excerpt="The renewal term is twelve months.",
    )
    execution = ExecutionResult(evidence=[evidence])
    result = synthesizer._from_candidate(
        {
            "answer": "The renewal term is twelve months [ev-1].",
            "citations": ["ev-1", "ev-999"],
            "confidence": 0.9,
        },
        execution,
    )

    assert [citation.source_id for citation in result.citations] == ["doc-1"]
    assert result.confidence == 0.9


@pytest.mark.asyncio
async def test_agent_pipeline_returns_answer_with_evidence() -> None:
    """The agent coordinates planner, executor, synthesis, and persistence."""
    pool = FakePool(data={"count": 1, "renewals": [{"contract_id": "c-1"}]})
    store = FakeStore()
    agent = AskAIAgent(
        FakeSettings(),  # type: ignore[arg-type]
        pool,  # type: ignore[arg-type]
        planner=AgentPlanner(enabled=False),
        synthesizer=AnswerSynthesizer(FakeSettings(), enabled=False),
        store=store,  # type: ignore[arg-type]
    )

    answer = await agent.answer(
        question="Which contracts renew in the next 90 days?",
        identity=IDENTITY,
        user_id="user-test",
        auto_execute_actions=True,
    )

    assert answer.conversation_id == store.conversation_id
    assert answer.tool_calls
    assert answer.evidence
    assert "Evidence retrieved" in answer.answer
    assert answer.plan_source == "heuristic"
    assert store.assistant_payloads
    assert pool.calls[0]["identity"].tenant_id == TENANT


@pytest.mark.asyncio
async def test_action_confirm_low_risk_does_not_mint_token() -> None:
    """Explicit confirmation of a low-risk write skips the HMAC token."""
    pool = FakePool(data={"status": "created", "workflow_id": "w-1"})
    service = ActionService(FakeSettings(), pool)  # type: ignore[arg-type]

    response = await service.confirm(
        identity=IDENTITY,
        tool="create_procurement_task",
        arguments={"title": "Review Adobe renewal"},
    )

    assert response["success"] is True
    assert response["expires_at"] is None
    sent = pool.calls[0]["arguments"]
    assert "confirmation_token" not in sent
    assert sent["dry_run"] is False


@pytest.mark.asyncio
async def test_action_confirm_high_risk_mints_tenant_bound_token() -> None:
    """Confirmation mints a token whose digest binds the reviewed arguments."""
    pool = FakePool(data={"status": "sent", "delivered": True})
    service = ActionService(FakeSettings(), pool)  # type: ignore[arg-type]

    response = await service.confirm(
        identity=IDENTITY,
        tool="send_email",
        arguments={
            "to": ["vendor@example.com"],
            "subject": "Renewal",
            "body": "Checking in",
        },
    )

    sent = pool.calls[0]["arguments"]
    assert response["expires_at"] is not None
    assert sent["confirmation_token"]
    assert sent["dry_run"] is False

    from zellovest_shared.mcp_confirmation import verify_confirmation_token

    verify_confirmation_token(
        token=sent["confirmation_token"],
        secret=FakeSettings().mcp_confirmation_secret,
        tenant_id=TENANT,
        tool_name="send_email",
        idempotency_key=sent["idempotency_key"],
        parameters=sent,
    )
