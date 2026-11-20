"""MCP-2 Document Knowledge server.

Provides semantic retrieval over indexed procurement documents plus precise
source inspection. It never exposes raw bucket listing, arbitrary object keys,
or vector-database browsing: every tool requires a tenant-scoped question,
document id, chunk id, or section, and every response carries provenance.

The distinction between source content (extracted pages, indexed passages) and
model-generated summaries is explicit in ``content_type`` on page/provenance
payloads (PRD 25.3).
"""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import UTC, datetime
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from zellovest_shared.config import get_settings
from zellovest_shared.db.models import ExtractionArtifact
from zellovest_shared.db.session import async_session_context
from zellovest_shared.db.transact import Document, ExtractionProvenance
from zellovest_shared.logging_conf import get_logger
from zellovest_shared.mcp_contracts import MCP_DOCUMENTS
from zellovest_shared.rag import search_documents as rag_search_documents
from zellovest_shared.workers.gcs_client import GcsStorageReader

from zellovest_mcp.errors import ErrorCode, ToolError, invalid, not_found
from zellovest_mcp.runtime import McpServerRuntime

logger = get_logger(__name__)

SERVER_NAME = MCP_DOCUMENTS
SERVER_VERSION = "1.0.0"

documents = McpServerRuntime(
    server_name=SERVER_NAME,
    display_name="Zellovest Document Knowledge MCP",
    version=SERVER_VERSION,
)


# ---------------------------------------------------------------------------
# Qdrant helpers (tenant filter mandatory)
# ---------------------------------------------------------------------------


def _qdrant_headers() -> dict[str, str]:
    """Return Qdrant auth headers from shared settings."""
    settings = get_settings()
    return {"api-key": settings.qdrant_api_key} if settings.qdrant_api_key else {}


async def _qdrant_scroll(
    *,
    tenant_id: str,
    limit: int,
    document_id: str | None = None,
    vendor_id: str | None = None,
    document_type: str | None = None,
    chunk_id: str | None = None,
    section: str | None = None,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """Scroll indexed passages with a hard tenant filter.

    Args:
        tenant_id: Owning tenant; always the first Qdrant filter.
        limit: Maximum results after integer offset slicing (bounded by caller).
        document_id: Optional structured document id.
        vendor_id: Optional vendor filter.
        document_type: Optional document type filter.
        chunk_id: Optional exact chunk id lookup.
        section: Optional case-insensitive section match.
        offset: Integer offset implemented by over-fetching then slicing.

    Returns:
        Payload dictionaries; empty when the collection does not exist yet.
    """
    settings = get_settings()
    must: list[dict[str, Any]] = [{"key": "tenant_id", "match": {"value": tenant_id}}]
    if document_id:
        must.append({"key": "document_id", "match": {"value": document_id}})
    if vendor_id:
        must.append({"key": "vendor_id", "match": {"value": vendor_id}})
    if document_type:
        must.append({"key": "document_type", "match": {"value": document_type}})
    if chunk_id:
        must.append({"key": "chunk_id", "match": {"value": chunk_id}})
    if section:
        must.append({"key": "section", "match": {"value": section}})

    fetch_limit = min(200, max(limit + offset, limit))
    base = settings.qdrant_url.rstrip("/")
    url = f"{base}/collections/{settings.qdrant_collection}/points/scroll"
    payload = {
        "filter": {"must": must},
        "limit": fetch_limit,
        "with_payload": True,
        "with_vector": False,
    }
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(url, headers=_qdrant_headers(), json=payload)
        if response.status_code == 404:
            return []
        response.raise_for_status()
        points = (response.json().get("result") or {}).get("points", [])
    return [(point.get("payload") or {}) for point in points[offset : offset + limit]]


def _chunk_payload(payload: dict[str, Any], *, score: float | None = None) -> dict[str, Any]:
    """Shape a Qdrant payload into a citation-ready chunk.

    Args:
        payload: Stored Qdrant payload.
        score: Optional fused retrieval score.

    Returns:
        Chunk dictionary with document, page, section, and bbox provenance.
    """
    chunk = {
        "chunk_id": str(payload.get("chunk_id") or ""),
        "parent_id": payload.get("parent_id"),
        "document_id": str(payload.get("document_id") or ""),
        "vendor_id": payload.get("vendor_id"),
        "document_type": payload.get("document_type"),
        "filename": payload.get("filename"),
        "page": payload.get("page"),
        "section": payload.get("section"),
        "bbox": payload.get("bbox"),
        "content": payload.get("content"),
        "parent_content": payload.get("parent_content"),
        "content_type": "source_extraction",
        "citation": _citation(payload),
    }
    if score is not None:
        chunk["score"] = round(float(score), 6)
    return chunk


def _citation(payload: dict[str, Any]) -> str:
    """Build a human-readable citation label for one passage."""
    filename = payload.get("filename") or "document"
    page = payload.get("page")
    section = payload.get("section")
    parts = [str(filename)]
    if page is not None:
        parts.append(f"p.{page}")
    if section:
        parts.append(str(section))
    return " - ".join(parts)


async def _semantic_search(
    context,
    *,
    query: str,
    vendor_id: str | None,
    document_type: str | None = None,
    document_types: list[str] | None = None,
    document_id: str | None = None,
    limit: int,
) -> list[dict[str, Any]]:
    """Run hybrid retrieval off the event loop and shape the citations."""
    try:
        passages = await asyncio.to_thread(
            rag_search_documents,
            tenant_id=context.tenant_id,
            query=query,
            vendor_id=vendor_id,
            document_type=document_type,
            document_types=document_types,
            document_id=document_id,
            limit=limit,
        )
    except Exception as exc:
        logger.error(
            "mcp_document_search_failed",
            tenant_id=context.tenant_id,
            error_class=type(exc).__name__,
        )
        raise ToolError(
            ErrorCode.INTEGRATION_UNAVAILABLE,
            "document index is temporarily unavailable",
            retryable=True,
        ) from exc
    return [_chunk_payload(payload, score=payload.get("score")) for payload in passages]


async def _document_row(
    session: AsyncSession, tenant_id: str, document_id: str
) -> Document:
    """Load one tenant-scoped document or raise a typed not-found error."""
    try:
        parsed = uuid.UUID(str(document_id))
    except (ValueError, TypeError) as exc:
        raise invalid("document_id must be a UUID") from exc
    document = await session.scalar(
        select(Document).where(Document.tenant_id == tenant_id, Document.id == parsed)
    )
    if document is None:
        raise not_found("document")
    return document


async def _artifact_row(
    session: AsyncSession, tenant_id: str, document: Document
) -> ExtractionArtifact | None:
    """Return the extraction-artifact metadata row for a document, if any."""
    if document.upload_id is None:
        return None
    return await session.scalar(
        select(ExtractionArtifact).where(
            ExtractionArtifact.tenant_id == tenant_id,
            ExtractionArtifact.upload_id == document.upload_id,
        )
    )


async def _artifact_payload(
    tenant_id: str, document: Document, row: ExtractionArtifact
) -> dict[str, Any] | None:
    """Download and parse a document's extraction artifact from object storage.

    Args:
        tenant_id: Owning tenant (used for logging only).
        document: Structured document row.
        row: Extraction artifact metadata row.

    Returns:
        Parsed artifact JSON, or None when the object is absent.

    Raises:
        ToolError: When object storage is configured but unavailable.
    """
    if not row.artifact_gcs_key:
        return None
    settings = get_settings()
    if not settings.gcs_raw_bucket:
        return None
    try:
        raw = await asyncio.to_thread(
            GcsStorageReader(settings.google_cloud_project).download_bytes,
            bucket=settings.gcs_raw_bucket,
            key=row.artifact_gcs_key,
        )
    except Exception as exc:
        logger.warning(
            "mcp_artifact_read_failed",
            tenant_id=tenant_id,
            document_id=str(document.id),
            error_class=type(exc).__name__,
        )
        raise ToolError(
            ErrorCode.INTEGRATION_UNAVAILABLE,
            "source artifact storage is temporarily unavailable",
            retryable=True,
        ) from exc
    if not raw:
        return None
    return json.loads(raw.decode("utf-8"))


# ---------------------------------------------------------------------------
# Search tools
# ---------------------------------------------------------------------------


@documents.tool("search_documents")
async def search_documents(context, arguments: dict[str, Any]) -> dict[str, Any]:
    """Semantic search across every indexed procurement document."""
    chunks = await _semantic_search(
        context,
        query=arguments["query"],
        vendor_id=arguments.get("vendor_id"),
        document_type=arguments.get("document_type"),
        limit=int(arguments.get("limit") or 8),
    )
    return {
        "chunks": chunks,
        "count": len(chunks),
        "as_of": datetime.now(UTC).isoformat(),
        "summary": (
            f"{len(chunks)} passages matched"
            if chunks
            else "no indexed passages matched this query"
        ),
    }


@documents.tool("search_contracts")
async def search_contracts(context, arguments: dict[str, Any]) -> dict[str, Any]:
    """Search contract passages, optionally including amendments."""
    if arguments.get("include_amendments", True):
        chunks = await _semantic_search(
            context,
            query=arguments["query"],
            vendor_id=arguments.get("vendor_id"),
            document_types=["contract", "amendment"],
            limit=int(arguments.get("limit") or 8),
        )
    else:
        chunks = await _semantic_search(
            context,
            query=arguments["query"],
            vendor_id=arguments.get("vendor_id"),
            document_type="contract",
            limit=int(arguments.get("limit") or 8),
        )
    return {
        "chunks": chunks,
        "count": len(chunks),
        "as_of": datetime.now(UTC).isoformat(),
        "summary": f"{len(chunks)} contract passages matched",
    }


@documents.tool("search_invoices")
async def search_invoices(context, arguments: dict[str, Any]) -> dict[str, Any]:
    """Search extracted invoice documents."""
    chunks = await _semantic_search(
        context,
        query=arguments["query"],
        vendor_id=arguments.get("vendor_id"),
        document_type="invoice",
        limit=int(arguments.get("limit") or 8),
    )
    return {
        "chunks": chunks,
        "count": len(chunks),
        "as_of": datetime.now(UTC).isoformat(),
        "summary": f"{len(chunks)} invoice passages matched",
    }


@documents.tool("search_vendor_policies")
async def search_vendor_policies(context, arguments: dict[str, Any]) -> dict[str, Any]:
    """Search policy documents and other vendor paperwork."""
    chunks = await _semantic_search(
        context,
        query=arguments["query"],
        vendor_id=arguments.get("vendor_id"),
        document_types=["policy", "other"],
        limit=int(arguments.get("limit") or 8),
    )
    return {
        "chunks": chunks,
        "count": len(chunks),
        "as_of": datetime.now(UTC).isoformat(),
        "summary": f"{len(chunks)} policy passages matched",
    }


@documents.tool("search_document_chunks")
async def search_document_chunks(context, arguments: dict[str, Any]) -> dict[str, Any]:
    """Search passages with optional document, vendor, and type filters."""
    chunks = await _semantic_search(
        context,
        query=arguments["query"],
        vendor_id=arguments.get("vendor_id"),
        document_id=arguments.get("document_id"),
        document_type=arguments.get("document_type"),
        limit=int(arguments.get("limit") or 10),
    )
    offset = int(arguments.get("offset") or 0)
    sliced = chunks[offset:]
    return {
        "chunks": sliced,
        "count": len(sliced),
        "pagination": {"limit": int(arguments.get("limit") or 10), "offset": offset},
        "as_of": datetime.now(UTC).isoformat(),
        "summary": f"{len(sliced)} passages matched",
    }


# ---------------------------------------------------------------------------
# Source inspection tools
# ---------------------------------------------------------------------------


@documents.tool("get_document")
async def get_document(context, arguments: dict[str, Any]) -> dict[str, Any]:
    """Return document metadata, extraction status, and field provenance."""
    async with async_session_context() as session:
        document = await _document_row(session, context.tenant_id, arguments["document_id"])
        provenance: list[dict[str, Any]] = []
        if arguments.get("include_provenance", True):
            rows = (
                await session.scalars(
                    select(ExtractionProvenance)
                    .where(
                        ExtractionProvenance.tenant_id == context.tenant_id,
                        ExtractionProvenance.document_id == document.id,
                    )
                    .order_by(ExtractionProvenance.field_name)
                    .limit(100)
                )
            ).all()
            provenance = [
                {
                    "entity_type": row.entity_type,
                    "entity_id": str(row.entity_id),
                    "field_name": row.field_name,
                    "field_value": row.field_value_text,
                    "confidence": float(row.confidence) if row.confidence is not None else None,
                    "page": row.page,
                    "bbox": row.bbox_json,
                    "extraction_method": row.extraction_method,
                    "content_type": "source_extraction",
                }
                for row in rows
            ]
        artifact_row = await _artifact_row(session, context.tenant_id, document)
        artifact_available = bool(artifact_row and artifact_row.artifact_gcs_key)
        return {
            "document": {
                "id": str(document.id),
                "filename": document.filename,
                "document_type": document.document_type.value,
                "status": document.status.value,
                "mime_type": document.mime_type,
                "vendor_id": str(document.vendor_id) if document.vendor_id else None,
                "page_count": document.page_count,
                "classifier_confidence": (
                    float(document.classifier_confidence)
                    if document.classifier_confidence is not None
                    else None
                ),
                "created_at": document.created_at.isoformat(),
                "updated_at": document.updated_at.isoformat(),
                "artifact_available": artifact_available,
                "extraction_method": artifact_row.extraction_method if artifact_row else None,
                "text_chars": artifact_row.text_chars if artifact_row else None,
            },
            "provenance": provenance,
            "as_of": datetime.now(UTC).isoformat(),
            "summary": (
                f"{document.filename}: {document.document_type.value}, "
                f"{document.page_count or 0} pages"
            ),
        }


@documents.tool("get_document_page")
async def get_document_page(context, arguments: dict[str, Any]) -> dict[str, Any]:
    """Return extracted blocks, tables, and bboxes for one source page."""
    page_number = int(arguments["page"])
    async with async_session_context() as session:
        document = await _document_row(session, context.tenant_id, arguments["document_id"])
        artifact_row = await _artifact_row(session, context.tenant_id, document)
        if artifact_row is None:
            raise ToolError(
                ErrorCode.NOT_FOUND,
                "page text is not available for this document",
                details={"reason": "artifact_unavailable"},
            )
        artifact = await _artifact_payload(context.tenant_id, document, artifact_row)
        if artifact is None:
            raise ToolError(
                ErrorCode.NOT_FOUND,
                "page text is not available for this document",
                details={"reason": "artifact_unavailable"},
            )
        pages = (artifact.get("extraction") or {}).get("pages") or []
        page = next(
            (item for item in pages if int(item.get("page_number") or 0) == page_number),
            None,
        )
        if page is None:
            raise ToolError(
                ErrorCode.NOT_FOUND,
                f"page {page_number} does not exist in this document",
            )
        return {
            "document_id": str(document.id),
            "filename": document.filename,
            "page": page_number,
            "page_count": len(pages),
            "text": page.get("text") or "",
            "text_blocks": page.get("text_blocks") or [],
            "tables": page.get("tables") or [],
            "images": page.get("images") or [],
            "content_type": "source_extraction",
            "extraction_method": (
                artifact_row.extraction_method if artifact_row else None
            ),
            "provenance": {
                "document_id": str(document.id),
                "filename": document.filename,
                "page": page_number,
                "citation": f"{document.filename} - p.{page_number}",
            },
            "as_of": datetime.now(UTC).isoformat(),
            "summary": f"{document.filename} page {page_number}",
        }


@documents.tool("get_document_section")
async def get_document_section(context, arguments: dict[str, Any]) -> dict[str, Any]:
    """Return indexed passages belonging to a named document section."""
    async with async_session_context() as session:
        document = await _document_row(session, context.tenant_id, arguments["document_id"])
        chunks = await _qdrant_scroll(
            tenant_id=context.tenant_id,
            limit=int(arguments.get("limit") or 20),
            document_id=str(document.id),
            section=arguments["section"],
        )
        payloads = [_chunk_payload(payload) for payload in chunks]
        return {
            "document_id": str(document.id),
            "filename": document.filename,
            "section": arguments["section"],
            "chunks": payloads,
            "count": len(payloads),
            "as_of": datetime.now(UTC).isoformat(),
            "summary": f"{len(payloads)} passages in section {arguments['section']!r}",
        }


@documents.tool("get_document_chunks")
async def get_document_chunks(context, arguments: dict[str, Any]) -> dict[str, Any]:
    """List indexed passages for one document with stable pagination."""
    async with async_session_context() as session:
        document = await _document_row(session, context.tenant_id, arguments["document_id"])
        chunks = await _qdrant_scroll(
            tenant_id=context.tenant_id,
            limit=int(arguments.get("limit") or 25),
            offset=int(arguments.get("offset") or 0),
            document_id=str(document.id),
        )
        payloads = [_chunk_payload(payload) for payload in chunks]
        return {
            "document_id": str(document.id),
            "filename": document.filename,
            "chunks": payloads,
            "count": len(payloads),
            "pagination": {
                "limit": int(arguments.get("limit") or 25),
                "offset": int(arguments.get("offset") or 0),
            },
            "as_of": datetime.now(UTC).isoformat(),
            "summary": f"{len(payloads)} indexed passages",
        }


@documents.tool("get_source_provenance")
async def get_source_provenance(context, arguments: dict[str, Any]) -> dict[str, Any]:
    """Return the source document, page, section, bbox, and passage for a chunk."""
    chunk_id = str(arguments["chunk_id"])
    payloads = await _qdrant_scroll(
        tenant_id=context.tenant_id,
        limit=1,
        chunk_id=chunk_id,
    )
    if not payloads:
        raise not_found("chunk")
    payload = payloads[0]
    document_id = str(payload.get("document_id") or "")
    document_meta: dict[str, Any] | None = None
    if document_id:
        async with async_session_context() as session:
            document = await session.scalar(
                select(Document).where(
                    Document.tenant_id == context.tenant_id,
                    Document.id == uuid.UUID(document_id),
                )
            )
            if document is not None:
                document_meta = {
                    "id": str(document.id),
                    "filename": document.filename,
                    "document_type": document.document_type.value,
                    "status": document.status.value,
                    "vendor_id": str(document.vendor_id) if document.vendor_id else None,
                }
    return {
        "chunk_id": chunk_id,
        "document_id": document_id,
        "parent_id": payload.get("parent_id"),
        "page": payload.get("page"),
        "section": payload.get("section"),
        "bbox": payload.get("bbox"),
        "content_type": "source_extraction",
        "content": payload.get("content"),
        "parent_content": payload.get("parent_content"),
        "citation": _citation(payload),
        "document": document_meta,
        "as_of": datetime.now(UTC).isoformat(),
        "summary": f"provenance for chunk {chunk_id}",
    }


__all__ = ["SERVER_NAME", "SERVER_VERSION", "documents"]
