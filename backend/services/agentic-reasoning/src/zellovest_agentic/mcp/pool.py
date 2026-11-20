"""MCP host pool: routes tool calls to the three logical servers."""

from __future__ import annotations

import hashlib
import json
import time
from typing import Any

from zellovest_shared.mcp_contracts import (
    MCP_DOCUMENTS,
    MCP_EXTERNAL,
    MCP_PROCUREMENT,
    ToolContract,
)

from zellovest_agentic.config import AgenticReasoningSettings
from zellovest_agentic.mcp.audit import log_tool_invocation
from zellovest_agentic.mcp.client import (
    McpHostError,
    McpIdentity,
    McpServerClient,
    McpToolResult,
)
from zellovest_agentic.mcp.registry import ToolRegistry


class McpPool:
    """Own one client per logical MCP server and expose a unified call API."""

    def __init__(
        self,
        settings: AgenticReasoningSettings,
        *,
        clients: dict[str, McpServerClient] | None = None,
    ) -> None:
        """Create clients for MCP-1/2/3.

        Args:
            settings: Service settings containing URLs and transport controls.
            clients: Optional client overrides (tests).
        """
        self.settings = settings
        if clients is None:
            registry = ToolRegistry(settings.mcp_default_actor_role)
            common = {
                "service_token": settings.mcp_service_token,
                "registry": registry,
                "connect_timeout_seconds": settings.mcp_connect_timeout_seconds,
                "transport_grace_seconds": settings.mcp_transport_grace_seconds,
                "max_retries": settings.mcp_max_retries,
                "retry_backoff_seconds": settings.mcp_retry_backoff_seconds,
                "circuit_failure_threshold": settings.mcp_circuit_failure_threshold,
                "circuit_reset_seconds": settings.mcp_circuit_reset_seconds,
            }
            clients = {
                MCP_PROCUREMENT: McpServerClient(
                    server=MCP_PROCUREMENT,
                    url=settings.mcp_procurement_url,
                    **common,
                ),
                MCP_DOCUMENTS: McpServerClient(
                    server=MCP_DOCUMENTS,
                    url=settings.mcp_document_url,
                    **common,
                ),
                MCP_EXTERNAL: McpServerClient(
                    server=MCP_EXTERNAL,
                    url=settings.mcp_external_url,
                    **common,
                ),
            }
        self.clients = clients
        self.registry = ToolRegistry(settings.mcp_default_actor_role)

    def registry_for(self, role: str) -> ToolRegistry:
        """Return a catalog filtered for a caller's role."""
        return ToolRegistry(role)

    def _client(self, contract: ToolContract) -> McpServerClient:
        """Return the transport client for a contract's server."""
        client = self.clients.get(contract.server)
        if client is None:
            raise McpHostError(
                "unavailable",
                f"no client configured for {contract.server}",
                server=contract.server,
                tool=contract.name,
            )
        return client

    async def call_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        identity: McpIdentity,
        *,
        purpose: str | None = None,
        idempotency_key: str | None = None,
    ) -> McpToolResult:
        """Validate, authorize, invoke, and audit one MCP tool call.

        Args:
            tool_name: Tool to invoke.
            arguments: Arguments supplied by the planner or a user action.
            identity: Authenticated caller context.
            purpose: Optional planner rationale for the trace.
            idempotency_key: Explicit key for a write action. When omitted, a
                deterministic key is derived from the request.

        Returns:
            Structured tool result.

        Raises:
            McpHostError: For unknown/unauthorized tools and transport/tool
                failures.
        """
        registry = self.registry_for(identity.role)
        try:
            contract = registry.require(tool_name)
            prepared = dict(arguments or {})
            if contract.operation == "write":
                prepared.setdefault(
                    "idempotency_key",
                    idempotency_key or self._derived_idempotency_key(tool_name, prepared, identity),
                )
            validated = registry.validate(tool_name, prepared)
        except Exception as exc:
            from zellovest_agentic.mcp.registry import ToolValidationError

            if isinstance(exc, ToolValidationError):
                raise McpHostError(
                    "invalid_arguments",
                    exc.message,
                    tool=tool_name,
                ) from exc
            raise

        client = self._client(contract)
        started = time.perf_counter()
        try:
            result = await client.call_tool(contract, validated, identity)
        except McpHostError as exc:
            log_tool_invocation(
                identity=identity,
                server=contract.server,
                tool=contract.name,
                tool_version=contract.version,
                risk_class=contract.risk_class,
                operation=contract.operation,
                arguments_digest=_digest(validated),
                latency_ms=int((time.perf_counter() - started) * 1000),
                success=False,
                error_code=exc.code,
                purpose=purpose,
            )
            raise
        log_tool_invocation(
            identity=identity,
            server=result.server,
            tool=result.tool,
            tool_version=result.tool_version,
            risk_class=result.risk_class,
            operation=result.operation,
            arguments_digest=result.arguments_digest,
            latency_ms=result.latency_ms,
            success=True,
            result_size=result.result_size,
            attempts=result.attempts,
            purpose=purpose,
        )
        return result

    @staticmethod
    def _derived_idempotency_key(
        tool_name: str, arguments: dict[str, Any], identity: McpIdentity
    ) -> str:
        """Derive a stable idempotency key for a host-originated write."""
        payload = json.dumps(
            {
                "tool": tool_name,
                "arguments": arguments,
                "conversation": identity.correlation_id,
                "tenant": identity.tenant_id,
            },
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]

    def derive_idempotency_key(
        self, tool_name: str, arguments: dict[str, Any], identity: McpIdentity
    ) -> str:
        """Return the deterministic idempotency key for one planned write.

        Args:
            tool_name: Write tool being invoked.
            arguments: Arguments as proposed by the planner or user.
            identity: Caller context (tenant + conversation correlation).

        Returns:
            Hex key suitable for the MCP-3 idempotency contract.
        """
        return self._derived_idempotency_key(tool_name, arguments, identity)

    def health(self) -> dict[str, Any]:
        """Return circuit-breaker and endpoint health for ``/readyz``."""
        return {
            "servers": {
                server: client.health() for server, client in self.clients.items()
            }
        }

    async def aclose(self) -> None:
        """Release transport resources.

        Per-call sessions close themselves, so there is nothing persistent to
        tear down today. The hook exists for a future pooled transport.
        """
        return None


def _digest(arguments: dict[str, Any]) -> str:
    """Return a stable digest for failure-path audit lines."""
    return hashlib.sha256(
        json.dumps(arguments, sort_keys=True, separators=(",", ":"), default=str).encode(
            "utf-8"
        )
    ).hexdigest()[:32]


__all__ = ["McpPool"]
