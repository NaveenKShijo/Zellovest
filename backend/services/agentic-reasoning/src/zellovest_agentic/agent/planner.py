"""Intent classification and tool planning for Ask AI.

The planner turns a natural-language question plus authenticated context into
a short, validated tool plan. The LLM proposes; the host disposes:

* only tools visible to the caller's role are offered,
* every argument object is validated against the canonical JSON Schema,
* identity fields (``tenant_id`` and friends) are never accepted from a plan,
* a deterministic heuristic planner takes over when the model is unavailable
  so the product still returns honest, bounded retrieval instead of failing
  open or fabricating an answer.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from zellovest_shared.logging_conf import get_logger

from zellovest_agentic.agent.llm import AgentLLMError, complete_json
from zellovest_agentic.mcp.registry import ToolRegistry, ToolValidationError

logger = get_logger(__name__)

# Identity is resolved from the authenticated request and must never travel in
# tool arguments (PRD 25.5 / tenant boundary).
_IDENTITY_KEYS = frozenset(
    {"tenant_id", "tenant", "user_id", "actor_id", "actor_user_id", "deployment_id"}
)

PLANNER_SYSTEM_PROMPT = """\
You are the planning component of Zellovest, a procurement intelligence platform.

Your job is NOT to answer the question. Your job is to choose the smallest set of
MCP tools that would let a downstream analyst answer it truthfully.

Rules:
1. Use only tools from the supplied catalog. Never invent tool names.
2. Never include tenant_id, user_id, actor fields, or deployment_id in tool
   arguments. The platform supplies identity out of band.
3. Never invent ids (vendor, contract, invoice, document, exception). If the
   question names an entity but the context has no id, plan a search tool first.
4. Prefer authoritative structured tools for numbers (spend, renewals,
   utilization, exceptions, savings). Use document search for clauses, policy,
   terms, amendments, and anything that needs a quotation.
5. Combine tools only when the question genuinely spans domains. Maximum {max_steps} steps.
6. Write tools are actions. Include one only when the user explicitly asks for a
   task, reminder, workflow, message, or approval. Never plan a high-risk action
   as an automatic step: it will be shown to the human for confirmation.
7. Tool arguments must satisfy the supplied input schema exactly. Omit optional
   fields you do not need. Dates are ISO ``YYYY-MM-DD``.
8. If the question is unanswerable without more user input, return an empty
   steps list and put the missing detail in ``needs_clarification``.
9. For a compound question, split independent document topics into focused
   search queries, using a separate search step for each topic when needed.
   Keep explicit vendor and document constraints from the user's context on
   every applicable search. Do not infer an identifier or broaden a filter.

Return one JSON object:
{{
  "intent": "short snake_case label",
  "rationale": "one sentence, no sensitive values",
  "needs_clarification": null or "short question for the user",
  "steps": [
    {{"tool": "tool_name", "arguments": {{}}, "purpose": "why this call"}}
  ]
}}
"""


@dataclass(frozen=True)
class PlanStep:
    """One validated tool invocation proposed by the planner."""

    tool: str
    arguments: dict[str, Any]
    purpose: str = ""


@dataclass(frozen=True)
class Plan:
    """An ordered, bounded plan for one question."""

    intent: str
    steps: tuple[PlanStep, ...] = ()
    rationale: str = ""
    source: str = "llm"
    notes: tuple[str, ...] = ()
    needs_clarification: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


def _iso_today() -> str:
    """Return today's date in ISO form."""
    return datetime.now(UTC).date().isoformat()


def _year_bounds() -> tuple[str, str]:
    """Return the start and end of the current calendar year."""
    today = datetime.now(UTC).date()
    return f"{today.year}-01-01", f"{today.year}-12-31"


def _sanitize_arguments(arguments: Any) -> dict[str, Any]:
    """Drop identity keys and require a mapping of tool arguments."""
    if not isinstance(arguments, dict):
        return {}
    return {key: value for key, value in arguments.items() if key not in _IDENTITY_KEYS}


class AgentPlanner:
    """Plan tool usage with an LLM, falling back to deterministic routing."""

    def __init__(self, *, enabled: bool = True, max_steps: int = 6) -> None:
        """Configure planning limits.

        Args:
            enabled: When False, skip the LLM and use deterministic routing
                (used by tests and air-gapped deployments).
            max_steps: Hard cap on planned tool calls.
        """
        self.enabled = enabled
        self.max_steps = max(1, max_steps)

    def plan(
        self,
        *,
        question: str,
        context: dict[str, Any] | None,
        history: list[dict[str, str]] | None,
        registry: ToolRegistry,
    ) -> Plan:
        """Produce a validated plan for one question.

        Args:
            question: User question.
            context: Optional client context (for example ``vendor_id``).
            history: Recent conversation turns (role/content).
            registry: Role-filtered tool catalog.

        Returns:
            A plan whose steps are guaranteed to pass contract validation.
        """
        context = context or {}
        fallback = self.heuristic_plan(
            question=question, context=context, registry=registry, source="heuristic"
        )
        if not self.enabled:
            return fallback

        try:
            candidate = complete_json(
                PLANNER_SYSTEM_PROMPT.format(max_steps=self.max_steps),
                {
                    "question": question,
                    "context": context,
                    "recent_history": (history or [])[-6:],
                    "today": _iso_today(),
                    "tools": registry.planner_catalog(),
                },
            )
        except AgentLLMError as exc:
            logger.warning("agent_planner_llm_unavailable", error_class=type(exc).__name__)
            return Plan(
                intent=fallback.intent,
                steps=fallback.steps,
                rationale="deterministic routing (planning model unavailable)",
                source="heuristic_fallback",
                notes=(*fallback.notes, "planner_llm_unavailable"),
            )

        intent = str(candidate.get("intent") or "general_question")[:64]
        rationale = str(candidate.get("rationale") or "")[:500]
        clarification = candidate.get("needs_clarification")
        clarification = str(clarification)[:500] if clarification else None
        raw_steps = candidate.get("steps")
        notes: list[str] = []
        steps: list[PlanStep] = []
        if isinstance(raw_steps, list):
            for index, raw in enumerate(raw_steps[: self.max_steps], start=1):
                if not isinstance(raw, dict):
                    notes.append(f"step {index} ignored: not an object")
                    continue
                tool = str(raw.get("tool") or "").strip()
                arguments = _sanitize_arguments(raw.get("arguments"))
                contract = registry.get(tool)
                if not tool or contract is None:
                    notes.append(f"step {index} ignored: unavailable tool")
                    continue
                if contract.operation == "write":
                    # The planner reviews parameters, not transport metadata.
                    # The executor derives the real tenant/conversation-scoped
                    # idempotency key immediately before invocation.
                    arguments.setdefault("idempotency_key", "planner-pending-key")
                try:
                    validated = registry.validate(tool, arguments)
                except ToolValidationError as exc:
                    notes.append(f"step {index} ignored: {exc.message}")
                    continue
                steps.append(
                    PlanStep(
                        tool=tool,
                        arguments=validated,
                        purpose=str(raw.get("purpose") or "")[:300],
                    )
                )

        if not steps and clarification is None:
            notes.append("planner produced no valid steps; using deterministic routing")
            merged = Plan(
                intent=fallback.intent,
                steps=fallback.steps,
                rationale=fallback.rationale,
                source="heuristic_fallback",
                notes=(*notes, *fallback.notes),
            )
            return merged

        return Plan(
            intent=intent,
            steps=tuple(steps),
            rationale=rationale,
            source="llm",
            notes=tuple(notes),
            needs_clarification=clarification,
        )

    @staticmethod
    def heuristic_plan(
        *,
        question: str,
        context: dict[str, Any],
        registry: ToolRegistry,
        source: str = "heuristic",
    ) -> Plan:
        """Route common procurement question shapes without a model.

        This is intentionally conservative: it selects authoritative totals and
        document retrieval that are always safe to run, never writes.
        """
        text = question.lower()
        vendor_id = context.get("vendor_id")
        start_date, end_date = _year_bounds()
        steps: list[PlanStep] = []

        def add(tool: str, arguments: dict[str, Any], purpose: str) -> None:
            """Add a step when the role can use the tool and it validates."""
            if registry.get(tool) is None:
                return
            try:
                validated = registry.validate(tool, arguments)
            except ToolValidationError:
                return
            if any(step.tool == tool and step.arguments == validated for step in steps):
                return
            steps.append(PlanStep(tool, validated, purpose))

        asks_renewal = any(
            word in text
            for word in (
                "renew",
                "expir",
                "notice period",
                "notice deadline",
                "auto-renew",
                "auto renew",
                "termination",
            )
        )
        asks_spend = any(
            word in text
            for word in ("spend", "cost", "paid", "price", "budget", "invoice total")
        )
        asks_licence = any(
            word in text for word in ("license", "licence", "seat", "utilization", "unused")
        )
        asks_savings = any(word in text for word in ("saving", "overbilling", "shelfware"))
        asks_maverick = any(
            word in text for word in ("maverick", "unmanaged", "shadow", "overlap")
        )
        asks_exception = any(
            word in text for word in ("exception", "reconcil", "discrepan", "flagged", "variance")
        )
        asks_documents = any(
            word in text
            for word in (
                "contract",
                "clause",
                "term",
                "amendment",
                "policy",
                "agreement",
                "sow",
                "dpa",
                "quotation",
                "document",
            )
        )

        if asks_renewal:
            add(
                "find_renewals",
                {"days_ahead": 180, "badge": "all"},
                "authoritative renewal dates and notice deadlines",
            )
        if asks_spend:
            spend_args: dict[str, Any] = {
                "start_date": start_date,
                "end_date": end_date,
                "group_by": "month",
            }
            if vendor_id:
                spend_args["vendor_id"] = vendor_id
            add("calculate_spend", spend_args, "authoritative spend totals")
            if vendor_id:
                add(
                    "get_vendor_spend",
                    {"vendor_id": vendor_id},
                    "authoritative vendor spend",
                )
        if asks_licence and vendor_id:
            add(
                "get_license_usage",
                {"vendor_id": vendor_id, "inactive_days": 30},
                "license utilization and inactive seats",
            )
        if asks_savings:
            add("calculate_savings", {}, "deterministic savings ledger totals")
        if asks_maverick:
            add("get_maverick_spend", {"limit": 20, "days": 365}, "unmanaged SaaS detections")
        if asks_exception:
            exception_id = context.get("exception_id")
            if exception_id:
                add(
                    "get_reconciliation_exception",
                    {"exception_id": str(exception_id)},
                    "authoritative exception detail",
                )
            else:
                invoice_args: dict[str, Any] = {"query": question[:2000], "limit": 8}
                if vendor_id:
                    invoice_args["vendor_id"] = vendor_id
                add("search_invoices", invoice_args, "invoice evidence for the exception")
        if asks_documents or not steps:
            doc_args: dict[str, Any] = {"query": question[:2000], "limit": 8}
            if vendor_id:
                doc_args["vendor_id"] = vendor_id
            tool = (
                "search_contracts"
                if "contract" in text or "clause" in text
                else "search_documents"
            )
            add(tool, doc_args, "source passages with page provenance")

        if not steps:
            add(
                "search_documents",
                {"query": question[:2000], "limit": 8},
                "source passages with page provenance",
            )

        intent = (
            "renewal_review"
            if asks_renewal
            else "spend_analysis"
            if asks_spend
            else "document_research"
        )
        return Plan(
            intent=intent,
            steps=tuple(steps),
            rationale="keyword routing over authoritative read tools",
            source=source,
            notes=(),
        )


def plan_as_json(plan: Plan) -> str:
    """Serialize a plan for trace metadata without arguments' sensitive values."""
    return json.dumps(
        {
            "intent": plan.intent,
            "source": plan.source,
            "tools": [step.tool for step in plan.steps],
            "notes": list(plan.notes),
        },
        separators=(",", ":"),
    )


__all__ = ["AgentPlanner", "Plan", "PlanStep", "plan_as_json"]
