"""ASGI entry point for MCP-3 External Systems and Actions (port 8103)."""

from zellovest_mcp.external import external
from zellovest_mcp.runtime import configure_server_logging
from zellovest_mcp.settings import get_mcp_settings

configure_server_logging(get_mcp_settings())
app = external.build_app()
