"""Tool sandbox: schema-validated, risk-classed access to MCP tools.

This router never executes domain logic itself. It is a thin host surface over
the three MCP servers so operators and tests can inspect contracts and invoke
tools with the same validation, tenant scoping, timeout, and audit behavior the
agent uses.

High-risk tools are refused here on purpose: they may only run through
``POST /ask-ai/actions/confirm`` so explicit human confirmation and an HMAC
token are always involved (PRD 24 / 25.4).
"""

from __future__ import annotations

from datetime import UTC, datetime
import time
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from zellovest_agentic.api.deps import (
    build_mcp_identity,
    get_current_user,
    normalize_tenant_id,
)
from zellovest_agentic.mcp import McpHostError, McpPool
from zellovest_shared.db.models import User
from zellovest_shared.logging_conf import get_logger
from zellovest_shared.mcp_contracts import ToolContract

logger = get_logger(__name__)
router = APIRouter(prefix="/tools", tags=["tools"])


class ToolSchema(BaseModel):
    """Full MCP tool contract (PRD 25.7)."""

    name: str
    server: str
    description: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    auth_scope: str
    roles: list[str]
    risk_class: str
    operation: str
    tenant_scoped: bool
    timeout_seconds: float
    idempotent: bool
    requires_confirmation: bool
    evidence_behavior: str
    audit_event_type: str
    version: str


class ToolCallRequest(BaseModel):
    """Request to call a tool through the sandbox."""

    tool_name: str = Field(..., min_length=1)
    arguments: dict[str, Any] = Field(default_factory=dict)
    tenant_id: str = Field(..., min_length=1, max_length=128)
    correlation_id: UUID | None = None
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=128)
    dry_run: bool = False


class ToolCallResponse(BaseModel):
    """Tool call response with invocation metadata."""

    tool_name: str
    server: str
    risk_class: str
    success: bool
    result: dict[str, Any] | None = None
    error: str | None = None
    error_code: str | None = None
    execution_time_ms: int
    attempts: int = 1
    provenance: dict[str, Any] = Field(default_factory=dict)


def _pool(request: Request) -> McpPool:
    """Return the app-scoped MCP pool, creating it lazily for tests."""
    pool = getattr(request.app.state, "mcp_pool", None)
    if pool is None:
        from zellovest_agentic.config import get_agentic_reasoning_settings

        settings = getattr(request.app.state, "settings", None) or get_agentic_reasoning_settings()
        request.app.state.settings = settings
        pool = McpPool(settings)
        request.app.state.mcp_pool = pool
    return pool


def _as_schema(contract: ToolContract) -> ToolSchema:
    """Serialize a contract for the discovery endpoints."""
    metadata = contract.as_metadata()
    return ToolSchema(
        input_schema=contract.strict_input_schema(),
        output_schema=dict(contract.output_schema),
        **metadata,
    )


@router.get("", response_model=list[ToolSchema])
async def list_tools(
    request: Request,
    current_user: User = Depends(get_current_user),
) -> list[ToolSchema]:
    """List every MCP tool this role may invoke."""
    registry = _pool(request).registry_for(current_user.role or "procurement_member")
    return [_as_schema(contract) for contract in registry.all()]


@router.get("/{tool_name}", response_model=ToolSchema)
async def get_tool(
    tool_name: str,
    request: Request,
    current_user: User = Depends(get_current_user),
) -> ToolSchema:
    """Return one tool contract visible to this role."""
    registry = _pool(request).registry_for(current_user.role or "procurement_member")
    contract = registry.get(tool_name)
    if contract is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tool {tool_name} not found",
        )
    return _as_schema(contract)


@router.post("/call", response_model=ToolCallResponse)
async def call_tool(
    body: ToolCallRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
) -> ToolCallResponse:
    """Validate and invoke one MCP tool with tenant and risk enforcement."""
    tenant_id = normalize_tenant_id(current_user.tenant_id)
    if normalize_tenant_id(body.tenant_id) != tenant_id:
        raise HTTPException(status_code=403, detail="tenant context mismatch")

    registry = _pool(request).registry_for(current_user.role or "procurement_member")
    contract = registry.get(body.tool_name)
    if contract is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tool {body.tool_name} not found",
        )
    if contract.requires_confirmation:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "confirmation_required",
                "message": (
                    f"{body.tool_name} is high risk; confirm it with "
                    "POST /api/v1/ask-ai/actions/confirm"
                ),
            },
        )

    identity = build_mcp_identity(
        current_user,
        str(body.correlation_id or request.state.request_id),
    )
    arguments = dict(body.arguments)
    if contract.operation == "write":
        if body.idempotency_key:
            arguments["idempotency_key"] = body.idempotency_key
        arguments.setdefault(
            "idempotency_key",
            _pool(request).derive_idempotency_key(body.tool_name, arguments, identity),
        )
        arguments["dry_run"] = bool(body.dry_run)

    started = time.perf_counter()
    logger.info(
        "tool_sandbox_requested",
        tenant_id=tenant_id,
        tool=body.tool_name,
        risk_class=contract.risk_class,
        correlation_id=identity.correlation_id,
    )
    try:
        result = await _pool(request).call_tool(
            body.tool_name,
            arguments,
            identity,
            purpose="tool sandbox invocation",
            idempotency_key=arguments.get("idempotency_key"),
        )
    except McpHostError as exc:
        elapsed = int((time.perf_counter() - started) * 1000)
        status_code = {
            "forbidden": status.HTTP_403_FORBIDDEN,
            "not_found": status.HTTP_404_NOT_FOUND,
            "invalid_arguments": status.HTTP_422_UNPROCESSABLE_CONTENT,
            "conflict": status.HTTP_409_CONFLICT,
            "timeout": status.HTTP_504_GATEWAY_TIMEOUT,
            "unavailable": status.HTTP_503_SERVICE_UNAVAILABLE,
            "circuit_open": status.HTTP_503_SERVICE_UNAVAILABLE,
        }.get(exc.code, status.HTTP_502_BAD_GATEWAY)
        raise HTTPException(
            status_code=status_code,
            detail={
                "code": exc.code,
                "message": exc.message,
                "tool": body.tool_name,
                "server": contract.server,
                "execution_time_ms": elapsed,
            },
        ) from exc

    return ToolCallResponse(
        tool_name=result.tool,
        server=result.server,
        risk_class=result.risk_class,
        success=True,
        result=result.data,
        execution_time_ms=result.latency_ms,
        attempts=result.attempts,
        provenance={
            "tenant_id": tenant_id,
            "server": result.server,
            "tool_version": result.tool_version,
            "correlation_id": result.correlation_id,
            "as_of": datetime.now(UTC).isoformat(),
        },
    )


__all__ = ["router"]
