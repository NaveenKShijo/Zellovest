"""Local stdio MCP server for tenant-scoped document retrieval."""

from __future__ import annotations

import os
from typing import Any

from mcp.server.fastmcp import FastMCP

from zellovest_shared.rag import search_documents as retrieve_documents

mcp = FastMCP("zellovest-document-knowledge")


def _deployment_tenant() -> str:
    """Return the deployment tenant set by the server operator, never by the model."""
    tenant_id = os.getenv("ZELLOVEST_TENANT_ID", "").strip()
    if not tenant_id:
        raise RuntimeError("ZELLOVEST_TENANT_ID must be set for the MCP server")
    return tenant_id


@mcp.tool()
def search_document_chunks(
    query: str,
    vendor_id: str | None = None,
    document_type: str | None = None,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Search indexed contract passages and return source provenance."""
    safe_limit = max(1, min(int(limit), 20))
    return retrieve_documents(
        tenant_id=_deployment_tenant(),
        query=query,
        vendor_id=vendor_id,
        document_type=document_type,
        limit=safe_limit,
    )


@mcp.tool()
def search_vendor_contracts(
    query: str, vendor_id: str | None = None, limit: int = 10
) -> list[dict[str, Any]]:
    """Search contracts and amendments, optionally scoped to one vendor."""
    return search_document_chunks(
        query=query, vendor_id=vendor_id, limit=limit
    )


if __name__ == "__main__":
    mcp.run(transport="stdio")
