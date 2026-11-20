"""Role-aware tool catalog used by the MCP host.

The catalog is imported from :mod:`zellovest_shared.mcp_contracts`, the same
module the three MCP servers use. That makes the host and providers share one
source of truth for names, JSON Schemas, scopes, risk classes, and timeouts.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import jsonschema
from jsonschema import FormatChecker
from zellovest_shared.mcp_contracts import (
    MCP_DOCUMENTS,
    MCP_EXTERNAL,
    MCP_PROCUREMENT,
    TOOL_CONTRACTS,
    ToolContract,
    role_allows,
)

SERVER_KEYS: dict[str, str] = {
    MCP_PROCUREMENT: "procurement",
    MCP_DOCUMENTS: "documents",
    MCP_EXTERNAL: "external",
}


class ToolValidationError(ValueError):
    """Raised when a planned tool call violates its declared contract."""

    def __init__(self, tool: str, message: str) -> None:
        """Capture the offending tool and a safe validation message."""
        super().__init__(f"{tool}: {message}")
        self.tool = tool
        self.message = message


@dataclass(frozen=True)
class ToolSelection:
    """A validated tool call proposed by the planner."""

    tool: str
    arguments: dict[str, Any]
    purpose: str = ""

    @property
    def contract(self) -> ToolContract:
        """Return the canonical contract for this selection."""
        contract = TOOL_CONTRACTS.get(self.tool)
        if contract is None:  # pragma: no cover - guarded by construction
            raise ToolValidationError(self.tool, "unknown tool")
        return contract


class ToolRegistry:
    """Expose only the tools an authenticated role may invoke."""

    def __init__(self, role: str) -> None:
        """Build a registry filtered by the caller's role.

        Args:
            role: Authenticated application role (for example
                ``procurement_member``).
        """
        self.role = role
        self._contracts = {
            name: contract
            for name, contract in TOOL_CONTRACTS.items()
            if role_allows(role, contract.auth_scope)
        }

    def all(self) -> tuple[ToolContract, ...]:
        """Return every contract visible to this role."""
        return tuple(self._contracts.values())

    def get(self, tool_name: str) -> ToolContract | None:
        """Return one visible contract, or None when unknown/forbidden."""
        return self._contracts.get(tool_name)

    def require(self, tool_name: str) -> ToolContract:
        """Return a visible contract or raise a validation error."""
        contract = self.get(tool_name)
        if contract is None:
            raise ToolValidationError(
                tool_name,
                "tool is not available to this role",
            )
        return contract

    def validate(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Validate arguments against the canonical input schema.

        Args:
            tool_name: Tool to validate.
            arguments: Candidate arguments.

        Returns:
            A shallow copy safe to pass to the MCP server.

        Raises:
            ToolValidationError: When the tool is unavailable or arguments do
                not satisfy the declared JSON Schema.
        """
        contract = self.require(tool_name)
        candidate = dict(arguments or {})
        try:
            jsonschema.validate(
                instance=candidate,
                schema=contract.strict_input_schema(),
                format_checker=FormatChecker(),
            )
        except jsonschema.ValidationError as exc:
            path = ".".join(str(part) for part in exc.absolute_path) or "arguments"
            raise ToolValidationError(tool_name, f"{path}: {exc.message}") from exc
        return candidate

    def planner_catalog(self) -> list[dict[str, Any]]:
        """Return a compact catalog for the planning prompt.

        Full output schemas are omitted: the planner only needs to choose a
        tool and construct valid arguments. The host still validates against
        the full contract before invoking the server.
        """
        return [
            {
                "name": contract.name,
                "server": contract.server,
                "description": contract.description,
                "input_schema": contract.strict_input_schema(),
                "risk_class": contract.risk_class,
                "operation": contract.operation,
            }
            for contract in self._contracts.values()
        ]

    def openai_tools(self) -> list[dict[str, Any]]:
        """Return function-calling schemas if an LLM tool-call loop is used."""
        return [
            {
                "type": "function",
                "function": {
                    "name": contract.name,
                    "description": contract.description,
                    "parameters": contract.strict_input_schema(),
                },
            }
            for contract in self._contracts.values()
        ]

    def digest_catalog(self) -> str:
        """Return a stable digest of the visible catalog for trace metadata."""
        import hashlib

        encoded = json.dumps(
            [contract.name for contract in self._contracts.values()],
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()[:16]


__all__ = [
    "SERVER_KEYS",
    "ToolRegistry",
    "ToolSelection",
    "ToolValidationError",
]
