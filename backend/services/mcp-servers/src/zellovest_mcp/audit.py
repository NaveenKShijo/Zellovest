"""Audit sink for MCP tool invocations.

Every invocation produces a structured log line and, unless disabled, one
``audit_events`` row. The row contains identity, server/tool/version, risk
class, authorization outcome, latency, success, error class, and result size.
Arguments are represented by a SHA-256 digest only (no raw prompts, document
text, email bodies, or credentials).

Writing the audit row lives in the MCP server (which already owns database
access) rather than in the reasoning service, keeping the reasoning service
free of direct procurement-data access.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from typing import Any

from sqlalchemy import select
from zellovest_shared.db.intelligence import AuditEvent, RiskClass
from zellovest_shared.db.session import async_session_context
from zellovest_shared.logging_conf import get_logger
from zellovest_shared.mcp_contracts import ToolContract

from zellovest_mcp.context import RequestContext
from zellovest_mcp.settings import McpServerSettings

logger = get_logger(__name__)


def _digest(value: Any) -> str:
    """Return a stable digest of tool arguments for correlation."""
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:32]


def _risk(value: str) -> RiskClass:
    """Map the contract risk string onto the persisted enum."""
    try:
        return RiskClass(value)
    except ValueError:
        return RiskClass.READ_ONLY


def _actor_uuid(actor_id: str):
    """Return the actor UUID or None for the synthetic ``system`` actor."""
    from uuid import UUID

    if actor_id == "system":
        return None
    try:
        return UUID(actor_id)
    except (ValueError, TypeError):
        return None


async def record_invocation(
    *,
    settings: McpServerSettings,
    context: RequestContext,
    contract: ToolContract,
    arguments: dict[str, Any],
    success: bool,
    latency_ms: int,
    result_size: int | None,
    error_code: str | None = None,
    auth_result: str = "allowed",
) -> None:
    """Persist and log one auditable tool invocation.

    The database write is best-effort and time-boxed: an audit outage must not
    turn a successful read into a user-visible failure, but it is always
    emitted to structured logs.

    Args:
        settings: Process settings controlling the audit sink.
        context: Authenticated caller context.
        contract: Tool contract that governed the call.
        arguments: Raw tool arguments (hashed, never stored).
        success: Whether the tool produced a successful result.
        latency_ms: Wall-clock execution time in milliseconds.
        result_size: Serialized result size in bytes, when available.
        error_code: Stable error code for failed calls.
        auth_result: ``allowed`` or ``denied``.
    """
    parameters_digest = _digest(arguments)
    logger.info(
        "mcp_tool_invocation",
        mcp_server=contract.server,
        tool=contract.name,
        tool_version=contract.version,
        tenant_id=context.tenant_id,
        deployment_id=context.deployment_id,
        actor_id=context.actor_id,
        actor_role=context.role,
        correlation_id=context.correlation_id,
        risk_class=contract.risk_class,
        operation=contract.operation,
        auth_result=auth_result,
        success=success,
        error_code=error_code,
        latency_ms=latency_ms,
        result_size=result_size,
        parameters_digest=parameters_digest,
    )
    if not settings.audit_db_enabled:
        return
    try:
        async with asyncio.timeout(settings.audit_timeout_seconds):
            async with async_session_context() as session:
                actor_id = _actor_uuid(context.actor_id)
                if actor_id is not None:
                    from zellovest_shared.db.models import User

                    exists = await session.scalar(select(User.id).where(User.id == actor_id))
                    if exists is None:
                        actor_id = None
                session.add(
                    AuditEvent(
                        tenant_id=context.tenant_id,
                        actor_user_id=actor_id,
                        correlation_id=context.correlation_id,
                        mcp_server=contract.server,
                        tool_name=contract.name,
                        tool_version=contract.version,
                        risk_class=_risk(contract.risk_class),
                        auth_result=auth_result,
                        success=success,
                        error_class=error_code,
                        latency_ms=latency_ms,
                        result_size=result_size,
                    )
                )
                await session.commit()
    except Exception as exc:
        logger.warning(
            "mcp_audit_write_failed",
            tool=contract.name,
            correlation_id=context.correlation_id,
            error_class=type(exc).__name__,
        )
