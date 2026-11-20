"""ASGI entry point for MCP-2 Document Knowledge (port 8102)."""

from zellovest_mcp.documents import documents
from zellovest_mcp.runtime import configure_server_logging
from zellovest_mcp.settings import get_mcp_settings

configure_server_logging(get_mcp_settings())
app = documents.build_app()
