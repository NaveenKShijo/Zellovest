"""Ask AI orchestration: intent -> plan -> MCP tools -> synthesis.

This is the MCP host pipeline from PRD 25.5. The service owns conversation
state, planning, tool selection, orchestration, and synthesis. It never queries
PostgreSQL, the vector store, object storage, or an external system directly:
every domain fact and every side effect goes through one of the three MCP
servers.

High-risk actions are exposed as proposals. :class:`ActionService` mints the
HMAC confirmation token only when a signed-in user explicitly confirms the exact
tool and parameters, then invokes MCP-3 with that token.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from zellovest_shared.logging_conf import get_logger
from zellovest_shared.mcp_confirmation import mint_confirmation_token
from zellovest_shared.mcp_contracts import ToolContract

from zellovest_agentic.agent.conversation import ConversationStore
from zellovest_agentic.agent.executor import ExecutionResult, PlanExecutor
from zellovest_agentic.agent.planner import AgentPlanner
from zellovest_agentic.agent.synthesizer import AnswerSynthesizer, SynthesizedAnswer
from zellovest_agentic.config import AgenticReasoningSettings
from zellovest_agentic.mcp.client import McpHostError, McpIdentity
from zellovest_agentic.mcp.pool import McpPool
from zellovest_agentic.mcp.registry import ToolValidationError
from zellovest_agentic.schemas.ask_ai import (
    AnswerSections,
    Citation,
    DataGap,
    EvidenceItem,
    ProposedAction,
    ToolCall,
)
from zellovest_agentic.services.tracing import trace_span

logger = get_logger(__name__)

EmitFn = Callable[[dict[str, Any]], Awaitable[None]]


async def _emit(emit: EmitFn | None, event: dict[str, Any]) -> None:
    """Send one streaming event, never letting a closed stream break the turn."""
    if emit is None:
        return
    try:
        await emit(event)
    except Exception as exc:
        logger.debug("ask_ai_stream_emit_failed", error_class=type(exc).__name__)


@dataclass
class AgentAnswer:
    """Everything the API returns and the store persists for one turn."""

    answer: str
    conversation_id: uuid.UUID
    citations: list[Citation]
    tool_calls: list[ToolCall]
    confidence: float
    evidence: list[EvidenceItem]
    proposed_actions: list[ProposedAction]
    data_gaps: list[DataGap]
    sections: AnswerSections
    intent: str | None
    plan_source: str | None
    processing_time_ms: int
    trace_id: str
    synthesis_source: str


class AskAIAgent:
    """Coordinate planning, MCP execution, synthesis, and persistence."""

    def __init__(
        self,
        settings: AgenticReasoningSettings,
        pool: McpPool,
        *,
        planner: AgentPlanner | None = None,
        synthesizer: AnswerSynthesizer | None = None,
        store: ConversationStore | None = None,
    ) -> None:
        """Wire the agent stages.

        Args:
            settings: Service configuration.
            pool: MCP host pool.
            planner: Optional planner override (tests).
            synthesizer: Optional synthesizer override (tests).
            store: Optional conversation store override (tests).
        """
        self.settings = settings
        self.pool = pool
        self.planner = planner or AgentPlanner(max_steps=settings.agent_max_plan_steps)
        self.synthesizer = synthesizer or AnswerSynthesizer(settings)
        self.store = store or ConversationStore(
            enabled=settings.agent_conversation_persistence
        )
        self.executor = PlanExecutor(pool)

    async def answer(
        self,
        *,
        question: str,
        identity: McpIdentity,
        context: dict[str, Any] | None = None,
        conversation_id: str | uuid.UUID | None = None,
        user_id: str | uuid.UUID | None = None,
        auto_execute_actions: bool = True,
        emit: EmitFn | None = None,
    ) -> AgentAnswer:
        """Answer one question end to end.

        Args:
            question: Natural-language question.
            identity: Authenticated caller context propagated to MCP.
            context: Optional UI context (for example ``vendor_id``).
            conversation_id: Existing conversation to continue.
            user_id: Signed-in user id for persistence.
            auto_execute_actions: Allow low-risk writes requested by the user.
            emit: Optional async callback receiving pipeline events for SSE.

        Returns:
            AgentAnswer with evidence, gaps, and proposed actions.

        Raises:
            ConversationNotFound: When an explicit conversation id is unknown.
        """
        started = time.perf_counter()
        trace_id = uuid.uuid4().hex
        conversation_uuid = await self.store.resolve(
            tenant_id=identity.tenant_id,
            user_id=user_id,
            conversation_id=conversation_id,
            context=context,
            question=question,
        )
        await _emit(
            emit,
            {
                "type": "start",
                "conversation_id": str(conversation_uuid),
                "trace_id": trace_id,
            },
        )
        history = await self.store.history(
            tenant_id=identity.tenant_id,
            conversation_id=conversation_uuid,
            limit=self.settings.agent_history_turns,
        )
        await self.store.append_user(
            tenant_id=identity.tenant_id,
            conversation_id=conversation_uuid,
            user_id=user_id,
            content=question,
            correlation_id=identity.correlation_id,
        )

        registry = self.pool.registry_for(identity.role)
        with trace_span(
            "ask_ai.plan",
            {
                "trace_id": trace_id,
                "tenant_id": identity.tenant_id,
                "role": identity.role,
                "history_turns": len(history),
            },
        ) as plan_span:
            plan = await asyncio.to_thread(
                self.planner.plan,
                question=question,
                context=context,
                history=history,
                registry=registry,
            )
            if plan_span:
                plan_span.update(
                    metadata={
                        "intent": plan.intent,
                        "source": plan.source,
                        "tools": [step.tool for step in plan.steps],
                    }
                )
        await _emit(
            emit,
            {
                "type": "plan",
                "intent": plan.intent,
                "source": plan.source,
                "tools": [step.tool for step in plan.steps],
                "needs_clarification": plan.needs_clarification,
            },
        )

        with trace_span(
            "ask_ai.execute",
            {
                "trace_id": trace_id,
                "tenant_id": identity.tenant_id,
                "intent": plan.intent,
                "steps": len(plan.steps),
            },
        ) as execution_span:
            try:
                execution = await self.executor.execute(
                    plan,
                    identity,
                    auto_execute_actions=auto_execute_actions,
                )
            except Exception as exc:
                logger.exception(
                    "ask_ai_execution_failed",
                    tenant_id=identity.tenant_id,
                    correlation_id=identity.correlation_id,
                    error_class=type(exc).__name__,
                )
                execution = ExecutionResult(
                    data_gaps=[
                        DataGap(
                            code="internal",
                            message="tool execution failed; no domain data was changed",
                        )
                    ]
                )
            if execution_span:
                execution_span.update(
                    metadata={
                        "evidence": len(execution.evidence),
                        "gaps": len(execution.data_gaps),
                        "actions": len(execution.proposed_actions),
                    }
                )
        for call in execution.tool_calls:
            await _emit(
                emit,
                {
                    "type": "tool",
                    "tool": call.tool,
                    "server": call.server,
                    "risk_class": call.risk_class,
                    "success": call.success,
                    "error": call.error,
                },
            )
        if execution.proposed_actions:
            await _emit(
                emit,
                {
                    "type": "actions",
                    "proposed_actions": [
                        action.model_dump(mode="json")
                        for action in execution.proposed_actions
                    ],
                },
            )
        await _emit(emit, {"type": "status", "stage": "synthesizing"})

        with trace_span(
            "ask_ai.synthesize",
            {
                "trace_id": trace_id,
                "tenant_id": identity.tenant_id,
                "evidence": len(execution.evidence),
            },
        ) as synthesis_span:
            synthesis: SynthesizedAnswer = await asyncio.to_thread(
                self.synthesizer.synthesize,
                question=question,
                plan=plan,
                execution=execution,
                history=history,
            )
            if synthesis_span:
                synthesis_span.update(
                    metadata={
                        "source": synthesis.source,
                        "citations": len(synthesis.citations),
                        "confidence": synthesis.confidence,
                    }
                )
        await _emit(emit, {"type": "token", "content": synthesis.answer})
        if execution.data_gaps:
            await _emit(
                emit,
                {
                    "type": "gaps",
                    "data_gaps": [gap.model_dump(mode="json") for gap in execution.data_gaps],
                },
            )

        processing_time_ms = int((time.perf_counter() - started) * 1000)
        answer = AgentAnswer(
            answer=synthesis.answer,
            conversation_id=conversation_uuid,
            citations=synthesis.citations,
            tool_calls=execution.tool_calls,
            confidence=synthesis.confidence,
            evidence=execution.evidence,
            proposed_actions=execution.proposed_actions,
            data_gaps=execution.data_gaps,
            sections=synthesis.sections,
            intent=plan.intent,
            plan_source=plan.source,
            processing_time_ms=processing_time_ms,
            trace_id=trace_id,
            synthesis_source=synthesis.source,
        )
        await self.store.append_assistant(
            tenant_id=identity.tenant_id,
            conversation_id=conversation_uuid,
            user_id=user_id,
            content=answer.answer,
            correlation_id=identity.correlation_id,
            payload=self._payload(answer),
        )
        logger.info(
            "ask_ai_answered",
            tenant_id=identity.tenant_id,
            correlation_id=identity.correlation_id,
            trace_id=trace_id,
            intent=plan.intent,
            plan_source=plan.source,
            synthesis_source=synthesis.source,
            tools=[call.tool for call in execution.tool_calls],
            evidence_count=len(execution.evidence),
            gap_count=len(execution.data_gaps),
            proposed_actions=len(execution.proposed_actions),
            processing_time_ms=processing_time_ms,
        )
        return answer

    @staticmethod
    def _payload(answer: AgentAnswer) -> dict[str, Any]:
        """Serialize the structured half of an answer for storage."""
        return {
            "citations": [item.model_dump(mode="json") for item in answer.citations],
            "evidence": [item.model_dump(mode="json") for item in answer.evidence],
            "proposed_actions": [
                item.model_dump(mode="json") for item in answer.proposed_actions
            ],
            "data_gaps": [item.model_dump(mode="json") for item in answer.data_gaps],
            "tool_calls": [item.model_dump(mode="json") for item in answer.tool_calls],
            "sections": answer.sections.model_dump(mode="json"),
            "confidence": answer.confidence,
            "intent": answer.intent,
            "plan_source": answer.plan_source,
            "trace_id": answer.trace_id,
        }


class ActionService:
    """Preview and execute actions under explicit human control."""

    def __init__(self, settings: AgenticReasoningSettings, pool: McpPool) -> None:
        """Store settings and the MCP pool."""
        self.settings = settings
        self.pool = pool
        self.store = ConversationStore(
            enabled=settings.agent_conversation_persistence
        )

    def _confirmation_secret(self) -> str:
        """Return the HMAC secret shared with MCP-3."""
        return self.settings.mcp_confirmation_secret or self.settings.mcp_service_token

    def _require_write(self, identity: McpIdentity, tool: str) -> ToolContract:
        """Return a visible write contract or raise a controlled error."""
        registry = self.pool.registry_for(identity.role)
        try:
            contract = registry.require(tool)
        except ToolValidationError as exc:
            raise McpHostError(
                "forbidden",
                "tool is not available to this role",
                tool=tool,
            ) from exc
        if contract.operation != "write":
            raise McpHostError(
                "invalid_arguments",
                f"{tool} is not an action tool",
                server=contract.server,
                tool=tool,
            )
        return contract

    async def preview(
        self,
        *,
        identity: McpIdentity,
        tool: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        """Run a side-effect-free dry-run of a proposed action.

        Args:
            identity: Authenticated caller.
            tool: Write tool to preview.
            arguments: Parameters the user is reviewing.

        Returns:
            A dictionary with the contract metadata and the tool preview.
        """
        contract = self._require_write(identity, tool)
        prepared = dict(arguments)
        prepared.setdefault(
            "idempotency_key",
            self.pool.derive_idempotency_key(tool, prepared, identity),
        )
        prepared["dry_run"] = True
        prepared.pop("confirmation_token", None)
        result = await self.pool.call_tool(
            tool,
            prepared,
            identity,
            purpose="human review dry-run",
            idempotency_key=str(prepared["idempotency_key"]),
        )
        return {
            "tool": tool,
            "server": contract.server,
            "risk_class": contract.risk_class,
            "requires_confirmation": contract.requires_confirmation,
            "arguments": prepared,
            "preview": result.data,
        }

    async def confirm(
        self,
        *,
        identity: McpIdentity,
        tool: str,
        arguments: dict[str, Any],
        idempotency_key: str | None = None,
        conversation_id: str | uuid.UUID | None = None,
        user_id: str | uuid.UUID | None = None,
        note: str | None = None,
    ) -> dict[str, Any]:
        """Execute a proposed action after explicit human confirmation.

        High-risk actions additionally require an HMAC token minted here - only
        after the signed-in user confirmed the exact tool and parameters. The
        token binds tenant, tool, idempotency key, and a digest of the
        arguments. Low-risk actions may also be confirmed (for example when the
        caller disabled inline execution); they do not need a token.

        Args:
            identity: Authenticated caller (the human who confirmed).
            tool: Write tool.
            arguments: Exact parameters the human reviewed.
            idempotency_key: Optional key; derived deterministically otherwise.
            conversation_id: Conversation to append the action result to.
            user_id: Signed-in user id.
            note: Optional confirmation note (not sent to external systems).

        Returns:
            A dictionary with the tool result and confirmation expiry.

        Raises:
            McpHostError: For read-only tools, validation failures, or
                controlled transport/tool failures.
        """
        contract = self._require_write(identity, tool)
        prepared = dict(arguments)
        key = (
            idempotency_key
            or str(prepared.get("idempotency_key") or "")
            or self.pool.derive_idempotency_key(tool, prepared, identity)
        )
        prepared["idempotency_key"] = key
        prepared.pop("confirmation_token", None)
        prepared["dry_run"] = False
        registry = self.pool.registry_for(identity.role)
        registry.validate(tool, prepared)
        expires_at: float | None = None
        if contract.requires_confirmation:
            token, expires_at = mint_confirmation_token(
                secret=self._confirmation_secret(),
                tenant_id=identity.tenant_id,
                tool_name=tool,
                idempotency_key=key,
                parameters=prepared,
                ttl_seconds=self.settings.ask_ai_confirmation_ttl_seconds,
            )
            prepared["confirmation_token"] = token
        result = await self.pool.call_tool(
            tool,
            prepared,
            identity,
            purpose="human-confirmed action",
            idempotency_key=key,
        )
        conversation_uuid = None
        parsed_conversation = None
        try:
            parsed_conversation = uuid.UUID(str(conversation_id)) if conversation_id else None
        except (ValueError, TypeError):
            parsed_conversation = None
        if parsed_conversation is not None:
            conversation_uuid = parsed_conversation
            await self.store.append_assistant(
                tenant_id=identity.tenant_id,
                conversation_id=conversation_uuid,
                user_id=user_id,
                content=f"Confirmed action {tool}: {result.data.get('summary', 'completed')}",
                correlation_id=identity.correlation_id,
                payload={
                    "action": {
                        "tool": tool,
                        "risk_class": contract.risk_class,
                        "arguments": prepared,
                        "result": result.data,
                        "note": note,
                        "confirmed_by": identity.actor_id,
                        "expires_at": (
                            datetime.fromtimestamp(expires_at, UTC).isoformat()
                            if expires_at is not None
                            else None
                        ),
                    }
                },
            )
        logger.info(
            "ask_ai_action_confirmed",
            tenant_id=identity.tenant_id,
            correlation_id=identity.correlation_id,
            actor_id=identity.actor_id,
            tool=tool,
            risk_class=contract.risk_class,
            expires_at=expires_at,
        )
        return {
            "tool": tool,
            "server": contract.server,
            "risk_class": contract.risk_class,
            "success": True,
            "result": result.data,
            "error": None,
            "expires_at": (
                datetime.fromtimestamp(expires_at, UTC)
                if expires_at is not None
                else None
            ),
            "conversation_id": conversation_uuid,
        }


__all__ = ["ActionService", "AgentAnswer", "AskAIAgent"]
