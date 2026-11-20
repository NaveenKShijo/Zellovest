"""Structured host-side audit for MCP invocations.

The MCP servers own the durable ``audit_events`` rows (they already have
database access). The host emits a structured log line for every call so a
request can be reconstructed end-to-end by ``correlation_id`` without giving
the reasoning service direct access to procurement data.

Arguments and results are never logged verbatim: arguments are represented by
a SHA-256 digest and results by byte size / a short summary.
"""

from __future__ import annotations

from typing import Any

from zellovest_shared.logging_conf import get_logger

logger = get_logger(__name__)


def log_tool_invocation(
    *,
    identity: Any,
    server: str,
    tool: str,
    tool_version: str,
    risk_class: str,
    operation: str,
    arguments_digest: str,
    latency_ms: int,
    success: bool,
    error_code: str | None = None,
    result_size: int | None = None,
    attempts: int = 1,
    purpose: str | None = None,
) -> None:
    """Emit one auditable MCP invocation line.

    Args:
        identity: :class:`~zellovest_agentic.mcp.client.McpIdentity`.
        server: Logical MCP server id.
        tool: Tool name.
        tool_version: Contract version.
        risk_class: ``read_only``, ``low_risk``, or ``high_risk``.
        operation: ``read`` or ``write``.
        arguments_digest: Non-reversible digest of the arguments.
        latency_ms: End-to-end host latency.
        success: Whether the call produced structured data.
        error_code: Stable error code for failures.
        result_size: Serialized result size in bytes.
        attempts: Number of transport attempts (including retries).
        purpose: Planner-provided reason for the call (no sensitive content).
    """
    logger.info(
        "mcp_host_tool_invocation",
        tenant_id=getattr(identity, "tenant_id", None),
        deployment_id=getattr(identity, "deployment_id", None),
        actor_id=getattr(identity, "actor_id", None),
        actor_role=getattr(identity, "role", None),
        correlation_id=getattr(identity, "correlation_id", None),
        request_id=getattr(identity, "correlation_id", None),
        mcp_server=server,
        mcp_tool=tool,
        tool_version=tool_version,
        risk_class=risk_class,
        operation=operation,
        authorization_result="allowed" if success or error_code not in {"forbidden"} else "denied",
        success=success,
        error_code=error_code,
        latency_ms=latency_ms,
        result_size=result_size,
        attempts=attempts,
        arguments_digest=arguments_digest,
        purpose=purpose,
    )


__all__ = ["log_tool_invocation"]
