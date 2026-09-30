"""MCP host/client wiring.

The Agentic Reasoning Service is the MCP host/client for:
- MCP-1 Procurement Intelligence (structured data + analytics)
- MCP-2 Document Knowledge (RAG + provenance)
- MCP-3 External Systems (workflow actions)

Transports: stdio locally, Streamable HTTP in production (per PRD 25.6).
"""

# TODO: implement MCP client sessions, capability discovery, timeouts,
# correlation IDs, and audit logging per PRD 25.8 / 25.9.
