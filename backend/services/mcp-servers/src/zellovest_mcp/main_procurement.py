"""ASGI entry point for MCP-1 Procurement Intelligence (port 8101)."""

from zellovest_mcp.procurement import procurement
from zellovest_mcp.runtime import configure_server_logging
from zellovest_mcp.settings import get_mcp_settings

configure_server_logging(get_mcp_settings())
app = procurement.build_app()
