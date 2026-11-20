"""Tests for Ask AI and tenant resolution in Agentic Reasoning Service."""

import uuid
from unittest.mock import patch

from fastapi.testclient import TestClient
from zellovest_agentic.agent.agent import AgentAnswer
from zellovest_agentic.api.deps import get_current_user, normalize_tenant_id
from zellovest_agentic.main import create_app
from zellovest_agentic.schemas.ask_ai import AnswerSections, Citation
from zellovest_shared.db.models import User


def test_normalize_tenant_id():
    """Single-tenant default aliases map to 'default-org'."""
    assert normalize_tenant_id("default") == "default-org"
    assert normalize_tenant_id("default-org") == "default-org"
    assert normalize_tenant_id("") == "default-org"
    assert normalize_tenant_id(None) == "default-org"
    assert normalize_tenant_id("tenant-custom") == "tenant-custom"


def test_ask_ai_resolves_default_org_tenant():
    """Ask AI normalizes tenant and queries agent with 'default-org'."""
    app = create_app()

    fake_user = User(
        id=uuid.uuid4(),
        email="test@zellovest.ai",
        tenant_id="default",  # Legacy default
        role="procurement_member",
        is_active=True,
    )

    app.dependency_overrides[get_current_user] = lambda: fake_user
    client = TestClient(app)

    captured = {}

    async def fake_answer(*args, **kwargs):
        captured.update(kwargs)
        return AgentAnswer(
            answer="The total is USD 25,886.47.",
            conversation_id=uuid.uuid4(),
            citations=[
                Citation(
                    source_type="document",
                    source_id="d-1",
                    description="PO-2025-0010.pdf",
                    excerpt="PO-2025-0010 Total: USD 25,886.47",
                )
            ],
            tool_calls=[],
            confidence=0.95,
            evidence=[],
            proposed_actions=[],
            data_gaps=[],
            sections=AnswerSections(),
            intent="purchase_order_query",
            plan_source="heuristic",
            processing_time_ms=12,
            trace_id="tr-1",
            synthesis_source="heuristic",
        )

    with patch("zellovest_agentic.agent.AskAIAgent.answer", side_effect=fake_answer):
        response = client.post(
            "/api/v1/ask-ai",
            json={"question": "What is the total for PO-2025-0010?"},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["answer"] == "The total is USD 25,886.47."
    assert captured["identity"].tenant_id == "default-org"


def test_ask_ai_tenant_mismatch_rejected():
    """Providing a mismatched tenant_id in body is rejected with 403."""
    app = create_app()

    fake_user = User(
        id=uuid.uuid4(),
        email="test@zellovest.ai",
        tenant_id="default-org",
        role="procurement_member",
        is_active=True,
    )

    app.dependency_overrides[get_current_user] = lambda: fake_user
    client = TestClient(app)

    response = client.post(
        "/api/v1/ask-ai",
        json={
            "question": "What is the total?",
            "tenant_id": "other-tenant",
        },
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "tenant context mismatch"
