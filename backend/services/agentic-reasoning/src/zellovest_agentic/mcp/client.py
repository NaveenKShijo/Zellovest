"""MCP client transport for the Agentic Reasoning Service.

The host talks to the three logical MCP servers over **Streamable HTTP** in
deployed environments (PRD 25.6). A connection is opened per tool call: the
servers are stateless and derive tenant/actor identity from per-request
headers, so a long-lived connection would bind one tenant to every subsequent
call. Opening a per-call session keeps the authorization boundary correct.

Cross-cutting behavior implemented here:

* canonical input-schema validation before the call,
* per-tool timeouts (contract timeout + a small transport grace),
* bounded retries for idempotent/read-only calls only,
* a per-server circuit breaker so a failing integration cannot cascade,
* typed errors that distinguish "unavailable" from "zero results",
* correlation and request identifiers on every call.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import random
import time
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from mcp.shared.exceptions import McpError
from zellovest_shared.logging_conf import get_logger
from zellovest_shared.mcp_confirmation import parameters_digest
from zellovest_shared.mcp_contracts import ToolContract

from zellovest_agentic.mcp.registry import ToolRegistry, ToolValidationError

logger = get_logger(__name__)


class McpHostError(Exception):
    """A controlled MCP failure that the agent can reason about safely."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        server: str | None = None,
        tool: str | None = None,
        retryable: bool = False,
        details: dict[str, Any] | None = None,
    ) -> None:
        """Capture a stable error code and safe, user-visible message."""
        super().__init__(message)
        self.code = code
        self.message = message
        self.server = server
        self.tool = tool
        self.retryable = retryable
        self.details = details or {}

    def to_payload(self) -> dict[str, Any]:
        """Serialize the error for tool traces and API responses."""
        return {
            "code": self.code,
            "message": self.message,
            "server": self.server,
            "tool": self.tool,
            "retryable": self.retryable,
            "details": self.details,
        }


@dataclass(frozen=True)
class McpIdentity:
    """Authenticated caller identity propagated to MCP servers as headers."""

    tenant_id: str
    actor_id: str
    role: str
    correlation_id: str
    deployment_id: str | None = None
    actor_email: str | None = None

    def headers(self, service_token: str) -> dict[str, str]:
        """Build the transport headers for one MCP request."""
        headers = {
            "Authorization": f"Bearer {service_token}",
            "X-Tenant-Id": self.tenant_id,
            "X-Deployment-Id": self.deployment_id or self.tenant_id,
            "X-Actor-Id": self.actor_id,
            "X-Actor-Role": self.role,
            "X-Correlation-Id": self.correlation_id,
            "X-Request-Id": self.correlation_id,
        }
        if self.actor_email:
            headers["X-Actor-Email"] = self.actor_email
        return headers


@dataclass(frozen=True)
class McpToolResult:
    """A successful structured tool response plus invocation metadata."""

    server: str
    tool: str
    tool_version: str
    risk_class: str
    operation: str
    data: dict[str, Any]
    latency_ms: int
    attempts: int
    correlation_id: str
    arguments_digest: str
    result_size: int


class CircuitBreaker:
    """Small per-server circuit breaker.

    Opens after ``failure_threshold`` consecutive failures, rejects calls while
    ``reset_timeout`` has not elapsed, then allows one half-open probe.
    """

    def __init__(self, failure_threshold: int, reset_timeout_seconds: float) -> None:
        """Configure the breaker thresholds."""
        self.failure_threshold = failure_threshold
        self.reset_timeout_seconds = reset_timeout_seconds
        self.failures = 0
        self.opened_at: float | None = None
        self.half_open = False

    @property
    def state(self) -> str:
        """Return ``closed``, ``open``, or ``half_open``."""
        if self.opened_at is None:
            return "half_open" if self.half_open else "closed"
        if time.monotonic() - self.opened_at >= self.reset_timeout_seconds:
            return "half_open"
        return "open"

    def allow(self) -> bool:
        """Return True when a call may be attempted."""
        state = self.state
        if state == "open":
            return False
        if state == "half_open" and not self.half_open:
            self.half_open = True
        return True

    def record_success(self) -> None:
        """Close the breaker after a successful probe or call."""
        self.failures = 0
        self.opened_at = None
        self.half_open = False

    def record_failure(self) -> None:
        """Count a failure and open the breaker at the threshold."""
        self.failures += 1
        self.half_open = False
        if self.failures >= self.failure_threshold:
            self.opened_at = time.monotonic()


def _arguments_digest(arguments: dict[str, Any]) -> str:
    """Return a stable, non-reversible digest of tool arguments."""
    return parameters_digest(arguments)


def _error_from_result(result: Any, contract: ToolContract) -> McpHostError:
    """Convert an ``isError`` MCP result into a typed host error."""
    structured = getattr(result, "structuredContent", None) or {}
    error = structured.get("error") if isinstance(structured, dict) else None
    if isinstance(error, dict):
        return McpHostError(
            str(error.get("code") or "internal"),
            str(error.get("message") or "tool execution failed"),
            server=contract.server,
            tool=contract.name,
            retryable=bool(error.get("retryable")),
            details=error.get("details") if isinstance(error.get("details"), dict) else {},
        )
    text = " ".join(
        getattr(item, "text", "") for item in (getattr(result, "content", None) or [])
    ).strip()
    code, _, message = text.partition(":")
    return McpHostError(
        code.strip() or "internal",
        message.strip() or text or "tool execution failed",
        server=contract.server,
        tool=contract.name,
    )


def _is_retryable(error: McpHostError, contract: ToolContract, arguments: dict[str, Any]) -> bool:
    """Return True when a bounded retry is safe and could succeed."""
    if error.code in {
        "invalid_arguments",
        "not_found",
        "forbidden",
        "confirmation_required",
        "conflict",
    }:
        return False
    if not error.retryable and error.code not in {"timeout", "unavailable", "circuit_open"}:
        return False
    return bool(
        contract.idempotent
        or contract.operation == "read"
        or arguments.get("idempotency_key")
    )


class McpServerClient:
    """Streamable-HTTP client for one logical MCP server."""

    def __init__(
        self,
        *,
        server: str,
        url: str,
        service_token: str,
        registry: ToolRegistry,
        connect_timeout_seconds: float = 10.0,
        transport_grace_seconds: float = 5.0,
        max_retries: int = 2,
        retry_backoff_seconds: float = 0.25,
        circuit_failure_threshold: int = 3,
        circuit_reset_seconds: float = 30.0,
    ) -> None:
        """Configure the transport, retries, and breaker for one server."""
        self.server = server
        self.url = url
        self.service_token = service_token
        self.registry = registry
        self.connect_timeout_seconds = connect_timeout_seconds
        self.transport_grace_seconds = transport_grace_seconds
        self.max_retries = max_retries
        self.retry_backoff_seconds = retry_backoff_seconds
        self.breaker = CircuitBreaker(circuit_failure_threshold, circuit_reset_seconds)

    async def call_tool(
        self,
        contract: ToolContract,
        arguments: dict[str, Any],
        identity: McpIdentity,
    ) -> McpToolResult:
        """Invoke one tool with validation, timeout, retries, and breaker.

        Args:
            contract: Canonical contract for the tool.
            arguments: Tool arguments (never tenant identity).
            identity: Authenticated caller context.

        Returns:
            Structured result plus invocation metadata.

        Raises:
            McpHostError: For every controlled failure mode.
            ToolValidationError: When arguments violate the contract before
                any network call is made.
        """
        if contract.server != self.server:
            raise McpHostError(
                "invalid_arguments",
                f"{contract.name} is served by {contract.server}, not {self.server}",
                server=self.server,
                tool=contract.name,
            )
        try:
            validated = self.registry.validate(contract.name, arguments)
        except ToolValidationError as exc:
            raise McpHostError(
                "invalid_arguments",
                exc.message,
                server=self.server,
                tool=contract.name,
            ) from exc

        if not self.breaker.allow():
            raise McpHostError(
                "circuit_open",
                f"{self.server} is temporarily isolated after repeated failures",
                server=self.server,
                tool=contract.name,
                retryable=True,
            )

        digest = _arguments_digest(validated)
        deadline = contract.timeout_seconds + self.transport_grace_seconds
        last_error: McpHostError | None = None
        attempts = self.max_retries + 1
        for attempt in range(1, attempts + 1):
            started = time.perf_counter()
            try:
                result = await self._call_once(
                    contract=contract,
                    arguments=validated,
                    identity=identity,
                    deadline=deadline,
                )
            except McpHostError as exc:
                last_error = exc
                # Application-level rejections (validation, not found, forbidden,
                # confirmation) are not integration failures and must not trip
                # the per-server circuit breaker.
                if exc.code in {
                    "timeout",
                    "unavailable",
                    "circuit_open",
                    "internal",
                    "invalid_response",
                }:
                    self.breaker.record_failure()
                if attempt >= attempts or not _is_retryable(exc, contract, validated):
                    break
                await asyncio.sleep(
                    self.retry_backoff_seconds * (2 ** (attempt - 1))
                    + random.uniform(0, self.retry_backoff_seconds)
                )
                continue
            self.breaker.record_success()
            latency_ms = int((time.perf_counter() - started) * 1000)
            data = getattr(result, "structuredContent", None)
            if not isinstance(data, dict):
                raise McpHostError(
                    "invalid_response",
                    f"{contract.name} returned no structured content",
                    server=self.server,
                    tool=contract.name,
                )
            return McpToolResult(
                server=self.server,
                tool=contract.name,
                tool_version=contract.version,
                risk_class=contract.risk_class,
                operation=contract.operation,
                data=data,
                latency_ms=latency_ms,
                attempts=attempt,
                correlation_id=identity.correlation_id,
                arguments_digest=digest,
                result_size=len(json.dumps(data, default=str).encode("utf-8")),
            )

        assert last_error is not None
        raise last_error

    async def _call_once(
        self,
        *,
        contract: ToolContract,
        arguments: dict[str, Any],
        identity: McpIdentity,
        deadline: float,
    ) -> Any:
        """Execute exactly one MCP call inside the transport deadline."""
        headers = identity.headers(self.service_token)
        try:
            async with asyncio.timeout(deadline):
                async with streamablehttp_client(
                    self.url,
                    headers=headers,
                    timeout=self.connect_timeout_seconds,
                    sse_read_timeout=deadline,
                ) as (read_stream, write_stream, _):
                    async with ClientSession(
                        read_stream,
                        write_stream,
                        read_timeout_seconds=timedelta(seconds=deadline),
                    ) as session:
                        await session.initialize()
                        result = await session.call_tool(
                            contract.name,
                            arguments,
                            read_timeout_seconds=timedelta(seconds=deadline),
                        )
        except TimeoutError as exc:
            raise McpHostError(
                "timeout",
                f"{contract.name} exceeded its {contract.timeout_seconds:g}s timeout",
                server=self.server,
                tool=contract.name,
                retryable=True,
            ) from exc
        except McpError as exc:
            raise McpHostError(
                "unavailable",
                f"{self.server} rejected the request: {exc.error.message}",
                server=self.server,
                tool=contract.name,
                retryable=True,
            ) from exc
        except BaseExceptionGroup as exc:  # anyio task-group transport failures
            raise McpHostError(
                "unavailable",
                f"{self.server} is temporarily unavailable",
                server=self.server,
                tool=contract.name,
                retryable=True,
            ) from exc
        except (httpx.HTTPError, OSError) as exc:
            raise McpHostError(
                "unavailable",
                f"{self.server} is temporarily unavailable",
                server=self.server,
                tool=contract.name,
                retryable=True,
            ) from exc
        except Exception as exc:
            logger.warning(
                "mcp_transport_error",
                server=self.server,
                tool=contract.name,
                correlation_id=identity.correlation_id,
                error_class=type(exc).__name__,
            )
            raise McpHostError(
                "unavailable",
                f"{self.server} is temporarily unavailable",
                server=self.server,
                tool=contract.name,
                retryable=True,
            ) from exc

        if getattr(result, "isError", False):
            raise _error_from_result(result, contract)
        return result

    def health(self) -> dict[str, Any]:
        """Return non-sensitive transport health for readiness reporting."""
        return {
            "server": self.server,
            "url": self.url,
            "circuit": self.breaker.state,
            "consecutive_failures": self.breaker.failures,
        }


def _digest_text(value: str) -> str:
    """Small helper retained for callers that need a stable digest."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:32]


__all__ = [
    "CircuitBreaker",
    "McpHostError",
    "McpIdentity",
    "McpServerClient",
    "McpToolResult",
]
