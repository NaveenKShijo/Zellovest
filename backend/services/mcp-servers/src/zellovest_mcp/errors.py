"""Typed tool errors shared by the three MCP servers.

Tool failures are returned as MCP results with ``isError=True`` (never as an
empty success) so the reasoning service can tell "the data does not exist"
apart from "the data is unavailable" (PRD 25.8).
"""

from __future__ import annotations

from enum import StrEnum


class ErrorCode(StrEnum):
    """Stable error codes understood by the MCP host and the UI."""

    UNAUTHENTICATED = "unauthenticated"
    FORBIDDEN = "forbidden"
    INVALID_ARGUMENTS = "invalid_arguments"
    NOT_FOUND = "not_found"
    CONFLICT = "conflict"
    CONFIRMATION_REQUIRED = "confirmation_required"
    INTEGRATION_UNAVAILABLE = "integration_unavailable"
    TIMEOUT = "timeout"
    INTERNAL = "internal"


class ToolError(Exception):
    """A tool execution failure with a stable code and retry hint."""

    def __init__(
        self,
        code: ErrorCode,
        message: str,
        *,
        retryable: bool = False,
        details: dict | None = None,
    ) -> None:
        """Capture the failure code, safe message, and retry semantics.

        Args:
            code: Stable machine-readable code.
            message: Human-readable message safe to show to the user.
            retryable: True only when a bounded retry may succeed.
            details: Optional non-sensitive structured context.
        """
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable
        self.details = details or {}

    def to_payload(self) -> dict:
        """Serialize the error for ``structuredContent``."""
        return {
            "code": self.code.value,
            "message": self.message,
            "retryable": self.retryable,
            "details": self.details,
        }


def not_found(what: str) -> ToolError:
    """Build a non-retryable not-found error for one resource type."""
    return ToolError(ErrorCode.NOT_FOUND, f"{what} not found in this tenant")


def invalid(message: str) -> ToolError:
    """Build a non-retryable validation error."""
    return ToolError(ErrorCode.INVALID_ARGUMENTS, message)
