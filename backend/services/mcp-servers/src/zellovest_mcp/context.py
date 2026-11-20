"""Authenticated request context for MCP tool invocations.

Tenant and actor identity are never taken from tool arguments. They are
resolved from transport headers that the MCP host signs with the shared
internal service token, so a prompt-injected model cannot widen its own tenant
boundary (PRD 25.2 / 25.6).
"""

from __future__ import annotations

import hmac
import re
import uuid
from dataclasses import dataclass, field
from typing import Any

from zellovest_shared.mcp_contracts import role_allows

from zellovest_mcp.errors import ErrorCode, ToolError
from zellovest_mcp.settings import McpServerSettings

_TENANT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_CORRELATION_RE = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
_UUID_RE = re.compile(r"^[0-9a-fA-F-]{36}$")

HEADER_TOKEN = "authorization"
HEADER_TENANT = "x-tenant-id"
HEADER_DEPLOYMENT = "x-deployment-id"
HEADER_ACTOR = "x-actor-id"
HEADER_ACTOR_EMAIL = "x-actor-email"
HEADER_ROLE = "x-actor-role"
HEADER_CORRELATION = "x-correlation-id"


@dataclass(frozen=True)
class RequestContext:
    """Resolved identity and tracing context for one MCP request."""

    tenant_id: str
    deployment_id: str
    actor_id: str
    actor_email: str | None
    role: str
    correlation_id: str
    authenticated: bool = True
    extra: dict[str, Any] = field(default_factory=dict)

    def require_scope(self, scope: str) -> None:
        """Raise a forbidden error unless the caller's role grants ``scope``.

        Args:
            scope: Authorization scope declared by the tool contract.
        """
        if not role_allows(self.role, scope):
            raise ToolError(
                ErrorCode.FORBIDDEN,
                f"role {self.role!r} is not authorized for scope {scope!r}",
                details={"required_scope": scope},
            )


def _first(headers: dict[str, str], name: str) -> str | None:
    """Return a stripped header value, treating blanks as absent."""
    value = headers.get(name)
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def resolve_request_context(
    headers: dict[str, str], settings: McpServerSettings
) -> RequestContext:
    """Validate inbound headers and build the tool invocation context.

    Args:
        headers: Lower-cased transport headers.
        settings: Process settings containing the shared service token.

    Returns:
        A fully populated :class:`RequestContext`.

    Raises:
        ToolError: With ``unauthenticated`` when the shared token is missing or
            wrong, or ``invalid_arguments`` when the tenant/role is malformed.
    """
    authorization = _first(headers, HEADER_TOKEN)
    authenticated = False
    if authorization:
        scheme, _, supplied = authorization.partition(" ")
        if scheme.lower() != "bearer" or not supplied:
            raise ToolError(ErrorCode.UNAUTHENTICATED, "bearer token required")
        if not settings.service_token or not hmac.compare_digest(
            supplied.strip(), settings.service_token
        ):
            raise ToolError(ErrorCode.UNAUTHENTICATED, "invalid service token")
        authenticated = True
    elif not settings.allow_anonymous:
        raise ToolError(
            ErrorCode.UNAUTHENTICATED,
            "service token required; the MCP host must authenticate every request",
        )

    tenant_id = _first(headers, HEADER_TENANT) or settings.default_tenant_id
    if not _TENANT_RE.match(tenant_id):
        raise ToolError(ErrorCode.INVALID_ARGUMENTS, "invalid tenant header")

    deployment_id = _first(headers, HEADER_DEPLOYMENT) or tenant_id
    actor_id = _first(headers, HEADER_ACTOR) or "system"
    if actor_id != "system" and not _UUID_RE.match(actor_id):
        raise ToolError(ErrorCode.INVALID_ARGUMENTS, "invalid actor header")

    role = _first(headers, HEADER_ROLE) or settings.default_role
    correlation_id = _first(headers, HEADER_CORRELATION) or uuid.uuid4().hex
    if not _CORRELATION_RE.match(correlation_id):
        raise ToolError(ErrorCode.INVALID_ARGUMENTS, "invalid correlation id header")

    return RequestContext(
        tenant_id=tenant_id,
        deployment_id=deployment_id,
        actor_id=actor_id,
        actor_email=_first(headers, HEADER_ACTOR_EMAIL),
        role=role,
        correlation_id=correlation_id,
        authenticated=authenticated,
    )
