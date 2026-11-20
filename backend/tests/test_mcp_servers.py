"""Tests for the three logical MCP servers (PRD 25.1 - 25.4, 25.6 - 25.9)."""

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from starlette.testclient import TestClient
from zellovest_mcp.context import RequestContext
from zellovest_mcp.errors import ErrorCode, ToolError
from zellovest_mcp.external import _confirmation_secret, external
from zellovest_mcp.procurement import procurement
from zellovest_mcp.settings import McpServerSettings
from zellovest_shared.mcp_confirmation import mint_confirmation_token
from zellovest_shared.mcp_contracts import (
    MCP_PROCUREMENT,
    PROCUREMENT_ROLE,
)


def test_public_health_endpoints():
    """healthz is public and does not require bearer token."""
    proc_app = procurement.build_app()
    client = TestClient(proc_app)
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["server"] == MCP_PROCUREMENT


def test_contracts_discovery_endpoint_auth():
    """v1/contracts requires authentication with service token."""
    proc_app = procurement.build_app()
    client = TestClient(proc_app)
    settings = procurement.settings

    # Missing auth
    unauth = client.get("/v1/contracts")
    assert unauth.status_code == 401

    # Valid auth
    authed = client.get(
        "/v1/contracts",
        headers={
            "Authorization": f"Bearer {settings.service_token}",
            "X-Tenant-Id": "test-tenant",
            "X-Actor-Id": "system",
            "X-Actor-Role": PROCUREMENT_ROLE,
        },
    )
    assert authed.status_code == 200
    data = authed.json()
    assert data["server"] == MCP_PROCUREMENT
    assert len(data["tools"]) == 13


def test_procurement_tool_validation():
    """Invoking a tool with missing required args or bad types returns INVALID_ARGUMENTS."""
    # get_vendor_spend requires vendor_id
    with pytest.raises(ToolError) as exc_info:
        procurement._validate(procurement.contracts["get_vendor_spend"], {})
    assert exc_info.value.code == ErrorCode.INVALID_ARGUMENTS

    # Passing bad type
    with pytest.raises(ToolError) as exc_info:
        procurement._validate(
            procurement.contracts["get_vendor_spend"],
            {"vendor_id": 12345},  # should be string UUID
        )
    assert exc_info.value.code == ErrorCode.INVALID_ARGUMENTS


def test_scope_authorization_enforced():
    """Context without required scope raises FORBIDDEN."""
    context = RequestContext(
        tenant_id="test-tenant",
        deployment_id="test-tenant",
        actor_id="system",
        actor_email=None,
        role="custom_unauthorized_role",
        correlation_id="corr-1",
    )
    with pytest.raises(ToolError) as exc_info:
        context.require_scope("procurement.vendor.read")
    assert exc_info.value.code == ErrorCode.FORBIDDEN


@pytest.mark.asyncio
async def test_external_tools_dry_run_and_idempotency():
    """External tools support dry_run and require idempotency keys."""
    context = RequestContext(
        tenant_id="test-tenant",
        deployment_id="test-tenant",
        actor_id="system",
        actor_email=None,
        role=PROCUREMENT_ROLE,
        correlation_id="corr-1",
    )

    handler = external._handlers["create_procurement_task"]
    result = await handler(
        context,
        {
            "title": "Review Adobe Renewal",
            "idempotency_key": "idemp-key-12345",
            "dry_run": True,
        },
    )
    assert result["dry_run"] is True
    assert result["status"] == "dry_run"
    assert "workflow_id" in result


@pytest.mark.asyncio
async def test_external_tools_high_risk_requires_confirmation():
    """High-risk operations fail without valid confirmation token unless dry-run (PRD 25.4)."""
    context = RequestContext(
        tenant_id="test-tenant",
        deployment_id="test-tenant",
        actor_id="system",
        actor_email=None,
        role=PROCUREMENT_ROLE,
        correlation_id="corr-1",
    )

    handler = external._handlers["send_email"]

    # Dry-run does NOT require confirmation token
    dry_result = await handler(
        context,
        {
            "to": ["vendor@example.com"],
            "subject": "Contract Renewal Inquiry",
            "body": "Inquiring about upcoming terms.",
            "idempotency_key": "idemp-key-99999",
            "dry_run": True,
        },
    )
    assert dry_result["dry_run"] is True
    assert dry_result["status"] == "dry_run"

    # Actual execution WITHOUT token must raise CONFIRMATION_REQUIRED
    with pytest.raises(ToolError) as exc_info:
        await handler(
            context,
            {
                "to": ["vendor@example.com"],
                "subject": "Contract Renewal Inquiry",
                "body": "Inquiring about upcoming terms.",
                "idempotency_key": "idemp-key-99999",
                "dry_run": False,
            },
        )
    assert exc_info.value.code == ErrorCode.CONFIRMATION_REQUIRED


@pytest.mark.asyncio
async def test_external_tools_high_risk_with_valid_token():
    """High-risk execution succeeds with valid HMAC confirmation token."""
    context = RequestContext(
        tenant_id="test-tenant",
        deployment_id="test-tenant",
        actor_id="system",
        actor_email=None,
        role=PROCUREMENT_ROLE,
        correlation_id="corr-1",
    )

    secret = _confirmation_secret()
    email_params = {
        "to": ["vendor@example.com"],
        "subject": "Contract Renewal Inquiry",
        "body": "Inquiring about upcoming terms.",
        "idempotency_key": "idemp-key-99999",
        "dry_run": False,
    }

    # Mint token with the shared confirmation secret
    token, _ = mint_confirmation_token(
        secret=secret,
        tenant_id=context.tenant_id,
        tool_name="send_email",
        idempotency_key="idemp-key-99999",
        parameters={
            "to": ["vendor@example.com"],
            "subject": "Contract Renewal Inquiry",
            "body": "Inquiring about upcoming terms.",
            "idempotency_key": "idemp-key-99999",
        },
    )

    email_params["confirmation_token"] = token
    handler = external._handlers["send_email"]

    fake_settings = McpServerSettings(
        service_token=secret,
        confirmation_secret=secret,
        smtp_host="smtp.example.com",
        smtp_from_address="noreply@example.com",
        audit_db_enabled=False,
    )

    @asynccontextmanager
    async def fake_session_context():
        mock_session = AsyncMock()
        mock_session.scalar = AsyncMock(return_value=None)
        mock_session.add = MagicMock()
        mock_session.commit = AsyncMock()
        yield mock_session

    with patch("zellovest_mcp.external.get_mcp_settings", return_value=fake_settings), \
         patch("zellovest_mcp.external.async_session_context", fake_session_context), \
         patch("smtplib.SMTP"):
        result = await handler(context, email_params)
        assert result["delivered"] is True
        assert result["status"] == "sent"
