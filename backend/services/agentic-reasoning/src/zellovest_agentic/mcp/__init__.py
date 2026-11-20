"""MCP host/client wiring.

The Agentic Reasoning Service is the MCP host/client for:

* MCP-1 Procurement Intelligence (structured data + deterministic analytics)
* MCP-2 Document Knowledge (hybrid retrieval + provenance)
* MCP-3 External Systems (controlled reads and writes)

Streamable HTTP is used for every deployed call. Each request carries the
authenticated tenant/actor context and a correlation id; a per-call session
keeps that boundary correct for the stateless servers (PRD 25.5-25.6).
"""

from zellovest_agentic.mcp.client import (
    McpHostError,
    McpIdentity,
    McpServerClient,
    McpToolResult,
)
from zellovest_agentic.mcp.pool import McpPool
from zellovest_agentic.mcp.registry import ToolRegistry, ToolSelection, ToolValidationError

__all__ = [
    "McpHostError",
    "McpIdentity",
    "McpPool",
    "McpServerClient",
    "McpToolResult",
    "ToolRegistry",
    "ToolSelection",
    "ToolValidationError",
]
