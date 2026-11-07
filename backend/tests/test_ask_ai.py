"""Tests for Ask AI and tenant resolution in Agentic Reasoning Service."""

import os
import uuid
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from zellovest_agentic.api.deps import get_current_user, normalize_tenant_id
from zellovest_agentic.main import create_app
from zellovest_shared.db.models import User


def test_normalize_tenant_id():
    """Single-tenant default aliases map to 'default-org'."""
    assert normalize_tenant_id("default") == "default-org"
    assert normalize_tenant_id("default-org") == "default-org"
    assert normalize_tenant_id("") == "default-org"
    assert normalize_tenant_id(None) == "default-org"
    assert normalize_tenant_id("tenant-custom") == "tenant-custom"


def test_ask_ai_resolves_default_org_tenant():
    """Ask AI normalizes tenant and queries RAG with 'default-org'."""
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

    captured_args = {}

    def fake_search_documents(*args, **kwargs):
        captured_args.update(kwargs)
        return [
            {
                "chunk_id": "c-1",
                "document_id": "d-1",
                "filename": "PO-2025-0010.pdf",
                "page": 1,
                "section": "LINE ITEMS",
                "content": "PO-2025-0010 Total: USD 25,886.47",
                "parent_content": "PO-2025-0010 Total: USD 25,886.47",
                "score": 0.95,
            }
        ]

    def fake_answer_question(question, passages):
        assert len(passages) == 1
        return {
            "answer": "The total is USD 25,886.47.",
            "citations": [
                {
                    "source_type": "document",
                    "source_id": "d-1",
                    "description": "PO-2025-0010.pdf",
                    "excerpt": "PO-2025-0010 Total: USD 25,886.47",
                }
            ],
            "usage": {"input_tokens": 50, "output_tokens": 10},
        }

    with patch("zellovest_agentic.api.routers.ask_ai.search_documents", side_effect=fake_search_documents), \
         patch("zellovest_agentic.api.routers.ask_ai.answer_question", side_effect=fake_answer_question):
        response = client.post(
            "/api/v1/ask-ai",
            json={"question": "What is the total for PO-2025-0010?"},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["answer"] == "The total is USD 25,886.47."
    assert captured_args.get("tenant_id") == "default-org"


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
