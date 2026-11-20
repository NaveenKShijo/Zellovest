"""Comprehensive tests for Agentic Reasoning Service as MCP Host/Client (PRD 24, 25.5 - 25.9)."""

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from zellovest_agentic.agent import (
    ActionService,
    AgentAnswer,
    AgentPlanner,
    Plan,
    PlanExecutor,
    PlanStep,
)
from zellovest_agentic.agent.synthesizer import AnswerSynthesizer
from zellovest_agentic.api.deps import get_current_user
from zellovest_agentic.config import AgenticReasoningSettings
from zellovest_agentic.main import create_app
from zellovest_agentic.mcp import (
    McpHostError,
    McpIdentity,
    McpPool,
    McpServerClient,
    McpToolResult,
    ToolRegistry,
    ToolValidationError,
)
from zellovest_agentic.mcp.client import CircuitBreaker
from zellovest_agentic.schemas.ask_ai import (
    AnswerSections,
    DataGap,
    EvidenceItem,
)
from zellovest_shared.db.models import User
from zellovest_shared.mcp_contracts import (
    MCP_DOCUMENTS,
    MCP_EXTERNAL,
    MCP_PROCUREMENT,
    PROCUREMENT_ROLE,
    TOOL_CONTRACTS,
)


@pytest.fixture
def mock_identity():
    return McpIdentity(
        tenant_id="test-tenant",
        actor_id=str(uuid.uuid4()),
        role=PROCUREMENT_ROLE,
        correlation_id="corr-test-1",
        deployment_id="test-tenant",
        actor_email="analyst@zellovest.ai",
    )


def test_tool_registry_role_filtering_and_validation():
    """Registry only exposes tools allowed for the role, and validates schemas."""
    registry = ToolRegistry(PROCUREMENT_ROLE)
    assert len(registry.all()) == 33
    assert registry.get("get_vendor") is not None

    # Unknown tool raises ToolValidationError
    with pytest.raises(ToolValidationError):
        registry.require("nonexistent_tool")

    # Strict validation rejects additional unknown properties
    with pytest.raises(ToolValidationError):
        registry.validate("get_vendor", {"vendor_id": str(uuid.uuid4()), "unknown_field": 123})


def test_circuit_breaker_logic():
    """Circuit breaker trips open on threshold failures and allows half-open probes."""
    breaker = CircuitBreaker(failure_threshold=2, reset_timeout_seconds=0.1)
    assert breaker.allow() is True
    assert breaker.state == "closed"

    breaker.record_failure()
    assert breaker.allow() is True
    breaker.record_failure()
    # Now open
    assert breaker.state == "open"
    assert breaker.allow() is False

    # Simulate timeout
    breaker.opened_at = breaker.opened_at - 1.0  # past reset timeout
    assert breaker.state == "half_open"
    assert breaker.allow() is True

    breaker.record_success()
    assert breaker.state == "closed"


@pytest.mark.asyncio
async def test_mcp_client_retries_idempotent_only(mock_identity):
    """McpServerClient only retries idempotent or read-only tools on retryable errors."""
    registry = ToolRegistry(PROCUREMENT_ROLE)
    client = McpServerClient(
        server=MCP_PROCUREMENT,
        url="http://localhost:8101/mcp",
        service_token="test-token",
        registry=registry,
        max_retries=2,
        retry_backoff_seconds=0.01,
    )

    contract = TOOL_CONTRACTS["get_vendor"]
    attempts_made = 0

    async def fake_call_once(*args, **kwargs):
        nonlocal attempts_made
        attempts_made += 1
        raise McpHostError("timeout", "upstream timed out", server=MCP_PROCUREMENT, retryable=True)

    with patch.object(client, "_call_once", side_effect=fake_call_once):
        with pytest.raises(McpHostError) as exc_info:
            await client.call_tool(
                contract,
                {"vendor_name": "Adobe"},
                mock_identity,
            )
        assert exc_info.value.code == "timeout"
        # Initial attempt + 2 retries = 3 attempts total
        assert attempts_made == 3


@pytest.mark.asyncio
async def test_mcp_client_does_not_retry_validation_errors(mock_identity):
    """Non-retryable errors (e.g. invalid arguments) are never retried."""
    registry = ToolRegistry(PROCUREMENT_ROLE)
    client = McpServerClient(
        server=MCP_PROCUREMENT,
        url="http://localhost:8101/mcp",
        service_token="test-token",
        registry=registry,
        max_retries=2,
    )

    contract = TOOL_CONTRACTS["get_vendor_spend"]

    with pytest.raises(McpHostError) as exc_info:
        # Missing required vendor_id
        await client.call_tool(contract, {}, mock_identity)
    assert exc_info.value.code == "invalid_arguments"


@pytest.mark.asyncio
async def test_mcp_pool_routes_to_proper_server(mock_identity):
    """McpPool routes calls to the server declared in the contract."""
    settings = AgenticReasoningSettings()
    pool = McpPool(settings)

    mock_proc_client = AsyncMock()
    mock_doc_client = AsyncMock()
    mock_ext_client = AsyncMock()

    pool.clients = {
        MCP_PROCUREMENT: mock_proc_client,
        MCP_DOCUMENTS: mock_doc_client,
        MCP_EXTERNAL: mock_ext_client,
    }

    mock_proc_client.call_tool.return_value = McpToolResult(
        server=MCP_PROCUREMENT,
        tool="get_vendor",
        tool_version="1.0.0",
        risk_class="read_only",
        operation="read",
        data={"vendor": {"id": str(uuid.uuid4()), "name": "Datadog"}},
        latency_ms=15,
        attempts=1,
        correlation_id=mock_identity.correlation_id,
        arguments_digest="abc",
        result_size=50,
    )

    res = await pool.call_tool("get_vendor", {"vendor_name": "Datadog"}, mock_identity)
    assert res.data["vendor"]["name"] == "Datadog"
    assert mock_proc_client.call_tool.called
    assert not mock_doc_client.call_tool.called
    assert not mock_ext_client.call_tool.called


def test_planner_heuristic_routing_and_sanitization():
    """Planner strips identity keys from arguments and selects bounded tools."""
    planner = AgentPlanner(enabled=False, max_steps=4)
    registry = ToolRegistry(PROCUREMENT_ROLE)

    plan = planner.plan(
        question="How much did we spend on Salesforce this year?",
        context={"vendor_name": "Salesforce", "tenant_id": "malicious-tenant-injection"},
        history=[],
        registry=registry,
    )

    assert plan.intent is not None
    assert len(plan.steps) <= 4
    for step in plan.steps:
        assert "tenant_id" not in step.arguments
        assert "user_id" not in step.arguments


@pytest.mark.asyncio
async def test_plan_executor_proposes_high_risk_and_handles_failures(mock_identity):
    """Executor converts high-risk writes to proposals with dry-run, and tool errors to DataGaps."""
    settings = AgenticReasoningSettings()
    pool = McpPool(settings)
    executor = PlanExecutor(pool)

    # Mock tool call in pool
    async def fake_call_tool(tool_name, arguments, identity, **kwargs):
        if tool_name == "get_vendor":
            raise McpHostError("timeout", "database read timed out", server=MCP_PROCUREMENT, tool="get_vendor")
        if tool_name == "send_email":
            # Dry-run preview
            return McpToolResult(
                server=MCP_EXTERNAL,
                tool="send_email",
                tool_version="1.0.0",
                risk_class="high_risk",
                operation="write",
                data={"status": "dry_run", "preview": "Email preview"},
                latency_ms=20,
                attempts=1,
                correlation_id=identity.correlation_id,
                arguments_digest="xyz",
                result_size=30,
            )
        return McpToolResult(
            server=MCP_PROCUREMENT,
            tool=tool_name,
            tool_version="1.0.0",
            risk_class="read_only",
            operation="read",
            data={},
            latency_ms=10,
            attempts=1,
            correlation_id=identity.correlation_id,
            arguments_digest="123",
            result_size=10,
        )

    with patch.object(pool, "call_tool", side_effect=fake_call_tool):
        plan = Plan(
            intent="vendor_outreach",
            steps=(
                PlanStep(tool="get_vendor", arguments={"vendor_name": "Slack"}),
                PlanStep(
                    tool="send_email",
                    arguments={
                        "to": ["vendor@slack.com"],
                        "subject": "Renewal",
                        "body": "Renewal inquiry",
                        "idempotency_key": "idemp-test-email",
                    },
                ),
            ),
        )

        exec_result = await executor.execute(plan, mock_identity, auto_execute_actions=True)

        # Failure became a DataGap (no hallucination)
        assert len(exec_result.data_gaps) == 1
        assert exec_result.data_gaps[0].tool == "get_vendor"
        assert exec_result.data_gaps[0].code == "timeout"

        # High-risk action was NOT executed automatically; became a proposed action
        assert len(exec_result.proposed_actions) == 1
        action = exec_result.proposed_actions[0]
        assert action.tool == "send_email"
        assert action.requires_confirmation is True
        assert action.executed is False
        assert action.preview is not None


def test_synthesizer_evidence_grounding_and_gap_handling():
    """Synthesizer fallback produces grounded response acknowledging data gaps."""
    settings = AgenticReasoningSettings()
    synthesizer = AnswerSynthesizer(settings)

    from zellovest_agentic.agent.executor import ExecutionResult

    plan = Plan(intent="spend_query")
    execution = ExecutionResult(
        data_gaps=[
            DataGap(
                tool="get_vendor_spend",
                server=MCP_PROCUREMENT,
                code="timeout",
                message="procurement database timed out",
            )
        ],
        evidence=[
            EvidenceItem(
                evidence_id="ev-1",
                kind="document",
                title="Contract MSA.pdf",
                tool="search_documents",
                server=MCP_DOCUMENTS,
                excerpt="Section 4: Payment terms 30 days net.",
            )
        ],
    )

    result = synthesizer.synthesize(
        question="What were the spend and terms for Datadog?",
        plan=plan,
        execution=execution,
        history=[],
    )

    assert result.answer is not None
    assert len(result.citations) >= 1
    # Answers mention unavailable data rather than fabricating zero
    lower_ans = result.answer.lower()
    assert any(term in lower_ans for term in ["unavailable", "not available", "timed out", "timeout"])


@pytest.mark.asyncio
async def test_action_service_preview_and_confirm(mock_identity):
    """ActionService previews actions and verifies human confirmation before execution."""
    settings = AgenticReasoningSettings()
    pool = McpPool(settings)
    service = ActionService(settings, pool)

    mock_pool_call = AsyncMock()
    mock_pool_call.return_value = McpToolResult(
        server=MCP_EXTERNAL,
        tool="send_email",
        tool_version="1.0.0",
        risk_class="high_risk",
        operation="write",
        data={"delivered": True, "status": "sent"},
        latency_ms=45,
        attempts=1,
        correlation_id=mock_identity.correlation_id,
        arguments_digest="digest",
        result_size=40,
    )

    with patch.object(pool, "call_tool", mock_pool_call):
        # Preview
        preview = await service.preview(
            identity=mock_identity,
            tool="send_email",
            arguments={"to": ["a@b.com"], "subject": "Hi", "body": "Hello"},
        )
        assert preview["requires_confirmation"] is True
        assert preview["arguments"]["dry_run"] is True

        # Confirm
        confirmed = await service.confirm(
            identity=mock_identity,
            tool="send_email",
            arguments={"to": ["a@b.com"], "subject": "Hi", "body": "Hello"},
        )
        assert confirmed["success"] is True
        assert confirmed["tool"] == "send_email"
        assert mock_pool_call.called


def test_api_tools_endpoints():
    """Verify /api/v1/tools discovery and detail endpoints."""
    app = create_app()
    fake_user = User(
        id=uuid.uuid4(),
        email="analyst@zellovest.ai",
        tenant_id="default-org",
        role="procurement_member",
        is_active=True,
    )
    app.dependency_overrides[get_current_user] = lambda: fake_user
    client = TestClient(app)

    # List tools
    res = client.get("/api/v1/tools")
    assert res.status_code == 200
    tools = res.json()
    assert len(tools) == 33

    # Get single tool
    res_tool = client.get("/api/v1/tools/get_vendor")
    assert res_tool.status_code == 200
    assert res_tool.json()["name"] == "get_vendor"
    assert res_tool.json()["server"] == MCP_PROCUREMENT

    # Nonexistent tool -> 404
    assert client.get("/api/v1/tools/invalid_tool").status_code == 404


def test_api_ask_ai_stream_endpoint():
    """Verify /api/v1/ask-ai/stream yields valid SSE frames."""
    app = create_app()
    fake_user = User(
        id=uuid.uuid4(),
        email="analyst@zellovest.ai",
        tenant_id="default-org",
        role="procurement_member",
        is_active=True,
    )
    app.dependency_overrides[get_current_user] = lambda: fake_user
    client = TestClient(app)

    async def fake_answer(*args, **kwargs):
        emit = kwargs.get("emit")
        if emit:
            await emit({"type": "plan", "intent": "vendor_spend", "tools": ["get_vendor_spend"]})
            await emit({"type": "token", "content": "Here is the spend."})
        return AgentAnswer(
            answer="Here is the spend.",
            conversation_id=uuid.uuid4(),
            citations=[],
            tool_calls=[],
            confidence=0.9,
            evidence=[],
            proposed_actions=[],
            data_gaps=[],
            sections=AnswerSections(),
            intent="vendor_spend",
            plan_source="heuristic",
            processing_time_ms=25,
            trace_id="tr-test",
            synthesis_source="heuristic",
        )

    with patch("zellovest_agentic.agent.AskAIAgent.answer", side_effect=fake_answer):
        response = client.post(
            "/api/v1/ask-ai/stream",
            json={"question": "What is our spend?"},
        )
        assert response.status_code == 200
        assert "text/event-stream" in response.headers["content-type"]
        body = response.text
        assert "data: " in body
        assert "complete" in body
