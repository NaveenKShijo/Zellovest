"""Document chunking, Voyage embeddings, FastEmbed sparse vectors, and Qdrant IO."""

from __future__ import annotations

import hashlib
import itertools
import math
import re
import time
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any

import httpx

from zellovest_shared.logging_conf import get_logger

logger = get_logger(__name__)


class VoyageRateLimitError(RuntimeError):
    """Raised when Voyage asks the caller to retry after a rate limit."""

    def __init__(self, retry_after_seconds: int) -> None:
        super().__init__("Voyage AI rate limit reached")
        self.retry_after_seconds = max(retry_after_seconds, 1)


_DENSE_NAME = "dense"
_SPARSE_NAME = "sparse"
_DENSE_SIZE = 1024
_FASTEMBED_MODEL = "Qdrant/bm42-all-minilm-l6-v2-attentions"
_sparse_model: Any | None = None


def _rag_settings() -> Any:
    """Load shared RAG settings, including values from backend/.env."""
    from zellovest_shared.config import get_settings

    return get_settings()


@dataclass(frozen=True)
class Passage:
    """A child passage with its larger parent context and source provenance."""

    point_id: str
    parent_id: str
    content: str
    parent_content: str
    page: int | None
    section: str | None
    bbox: list[float] | None


def _sparse_encoder() -> Any:
    """Load the FastEmbed sparse model lazily so API startup needs no model download."""
    global _sparse_model
    if _sparse_model is None:
        try:
            from fastembed import SparseTextEmbedding
        except ImportError as exc:
            raise RuntimeError("Install the FastEmbed dependency to use hybrid search") from exc
        _sparse_model = SparseTextEmbedding(model_name=_FASTEMBED_MODEL)
    return _sparse_model


def _paragraphs(text: str, max_chars: int = 900, overlap_chars: int = 120) -> list[str]:
    """Split text at paragraph/sentence boundaries with a small overlap."""
    if max_chars < 2 or not 0 <= overlap_chars < max_chars // 2:
        raise ValueError("invalid chunk size or overlap")
    parts = [re.sub(r"\s+", " ", part).strip() for part in re.split(r"\n\s*\n", text)]
    parts = [part for part in parts if part]
    chunks: list[str] = []
    current = ""
    for part in parts:
        if current and len(part) > max_chars:
            chunks.append(current)
            current = ""
        while len(part) > max_chars:
            cut = part.rfind(" ", 0, max_chars)
            cut = cut if cut > max_chars // 2 else max_chars
            chunks.append(part[:cut].strip())
            part = part[max(0, cut - overlap_chars):].strip()
        candidate = f"{current}\n{part}" if current else part
        if len(candidate) > max_chars and current:
            chunks.append(current)
            overlap = current[-overlap_chars:] if overlap_chars else ""
            current = f"{overlap} {part}".strip()
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


def build_passages(artifact: dict[str, Any], *, document_id: str) -> list[Passage]:
    """Build page-specific section parents and table-aware, source-located children."""
    extraction = artifact.get("extraction") or {}
    pages = extraction.get("pages") or []
    if not pages and extraction.get("full_text"):
        pages = [{"page_number": 1, "text": extraction["full_text"]}]
    # The fourth element holds a table header to repeat on every child fragment.
    groups: list[tuple[str | None, list[tuple[int, str, list[float] | None, str | None]]]] = []
    heading_pattern = re.compile(
        r"(?m)^[ \t]*((?:\d+(?:\.\d+)*[.)]?[ \t]+)?[A-Z][A-Z\d ,/&()'\u2019-]{3,90})[ \t]*$"
    )
    active_section: str | None = None

    def add_block(
        section: str | None, page: int, text: str, bbox: list[float] | None,
        table_header: str | None = None,
    ) -> None:
        """Group adjacent section content within a bounded parent."""
        for piece in _paragraphs(text, max_chars=2800, overlap_chars=0):
            if table_header:
                piece = f"{table_header}\n{piece}"
            size = sum(len(item[1]) + 2 for item in groups[-1][1]) if groups else 0
            if (not groups or groups[-1][0] != section or groups[-1][1][-1][0] != page
                    or size + len(piece) > 3200):
                groups.append((section, []))
            groups[-1][1].append((page, piece, bbox, table_header))

    def valid_bbox(value: Any) -> list[float] | None:
        """Keep only nondegenerate source coordinates."""
        if not isinstance(value, list) or len(value) != 4:
            return None
        try:
            box = [float(item) for item in value]
        except (TypeError, ValueError):
            return None
        if not all(math.isfinite(item) for item in box) or box[2] <= box[0] or box[3] <= box[1]:
            return None
        return box

    def mostly_in_table(box: list[float], table_box: list[float]) -> bool:
        """Detect text blocks largely contained in an extracted table."""
        width = max(0.0, min(box[2], table_box[2]) - max(box[0], table_box[0]))
        height = max(0.0, min(box[3], table_box[3]) - max(box[1], table_box[1]))
        return width * height / ((box[2] - box[0]) * (box[3] - box[1])) >= 0.7

    for page_data in pages:
        page = int(page_data.get("page_number") or 1)
        page_text = str(page_data.get("text") or "")
        tables = [table for table in page_data.get("tables") or [] if table.get("data")]
        table_boxes = [box for table in tables if (box := valid_bbox(table.get("bbox")))]
        text_blocks = [block for block in page_data.get("text_blocks") or []
                       if str(block.get("text") or "").strip()]
        def compact(text: str) -> str:
            """Measure extracted text coverage independent of whitespace."""
            return re.sub(r"\s+", "", text)
        block_length = sum(len(compact(str(block.get("text") or ""))) for block in text_blocks)
        use_blocks = bool(text_blocks) and (
            not page_text or block_length >= len(compact(page_text)) * 0.8
        )
        elements: list[tuple[float, int, str, Any]] = []
        if use_blocks:
            for order, block in enumerate(text_blocks):
                box = valid_bbox(block.get("bbox"))
                if box and any(mostly_in_table(box, table_box) for table_box in table_boxes):
                    continue
                elements.append((box[1] if box else float(order), order, "text", block))
        elif page_text:
            elements.append((0, 0, "text", {"text": page_text}))
        for order, table in enumerate(tables):
            box = valid_bbox(table.get("bbox"))
            elements.append((box[1] if box and use_blocks else float("inf"), order, "table", table))
        for _, _, kind, element in sorted(elements, key=lambda item: (item[0], item[1])):
            if kind == "text":
                text = str(element.get("text") or "")
                box = valid_bbox(element.get("bbox"))
                cursor = 0
                for match in heading_pattern.finditer(text):
                    add_block(active_section, page, text[cursor:match.start()].strip(), box)
                    active_section = match.group(1).strip()
                    cursor = match.end()
                add_block(active_section, page, text[cursor:].strip(), box)
                continue
            table = element
            rows = table.get("data") or []
            header = " | ".join(str(cell or "") for cell in rows[0])
            if len(rows) == 1:
                add_block(active_section, page, header, valid_bbox(table.get("bbox")))
                continue
            for row in rows[1:]:
                row_text = " | ".join(str(cell or "") for cell in row)
                add_block(active_section, page, row_text, valid_bbox(table.get("bbox")), header)
    passages: list[Passage] = []
    for section, blocks in groups:
        parent_text = "\n\n".join(block[1] for block in blocks)
        parent_id = str(uuid.uuid5(
            uuid.NAMESPACE_URL, f"{document_id}:{blocks[0][0]}:{section}:{parent_text}"
        ))
        index = 0
        for page, text, bbox, table_header in blocks:
            if table_header:
                row_text = text[len(table_header):].lstrip("\n")
                chunk_size = max(100, 500 - len(table_header) - 1)
                fragments = [f"{table_header}\n{part}" for part in
                             _paragraphs(row_text, max_chars=chunk_size,
                                         overlap_chars=min(60, chunk_size // 4))]
            else:
                fragments = _paragraphs(text, max_chars=500, overlap_chars=60)
            for content in fragments:
                digest = hashlib.sha1(content.encode("utf-8")).hexdigest()[:12]
                point_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{parent_id}:{index}:{digest}"))
                passages.append(
                    Passage(point_id, parent_id, content, parent_text, page, section, bbox)
                )
                index += 1
    return passages


def _qdrant_url() -> str:
    """Return the configured Qdrant base URL."""
    return _rag_settings().qdrant_url.rstrip("/")


def _qdrant_headers() -> dict[str, str]:
    """Return headers including the optional Qdrant API key."""
    key = _rag_settings().qdrant_api_key
    return {"api-key": key} if key else {}


def _ensure_collection(client: httpx.Client, collection: str) -> None:
    """Create a Qdrant collection with dense and named sparse vectors if absent."""
    response = client.get(f"{_qdrant_url()}/collections/{collection}", headers=_qdrant_headers())
    if response.status_code not in {200, 404}:
        response.raise_for_status()
    if response.status_code == 404:
        response = client.put(
            f"{_qdrant_url()}/collections/{collection}",
            headers=_qdrant_headers(),
            json={
                "vectors": {_DENSE_NAME: {"size": _DENSE_SIZE, "distance": "Cosine"}},
                "sparse_vectors": {_SPARSE_NAME: {}},
            },
        )
        if response.status_code in {400, 409}:
            # Another worker may have created the same collection concurrently.
            existing = client.get(
                f"{_qdrant_url()}/collections/{collection}", headers=_qdrant_headers()
            )
            if existing.status_code != 200:
                response.raise_for_status()
        else:
            response.raise_for_status()
    for field_name in ("tenant_id", "vendor_id", "document_type", "document_id",
                       "index_state", "record_type", "generation"):
        response = client.put(
            f"{_qdrant_url()}/collections/{collection}/index",
            headers=_qdrant_headers(),
            json={"field_name": field_name, "field_schema": "keyword"},
        )
        if response.status_code not in {200, 201, 409}:
            response.raise_for_status()


def _voyage_embeddings(texts: list[str], *, input_type: str) -> list[list[float]]:
    """Request Voyage embeddings for a batch of passages or queries."""
    settings = _rag_settings()
    api_key = settings.voyage_api_key
    if not api_key:
        raise RuntimeError("VOYAGE_API_KEY is required for document search")
    embeddings = []
    for offset in range(0, len(texts), 64):
        batch = texts[offset:offset + 64]
        response = httpx.post(
            settings.voyage_api_url,
            headers={"Authorization": f"Bearer {api_key}"},
            json={"model": settings.voyage_model, "input": batch,
                  "input_type": input_type},
            timeout=60,
        )
        if response.status_code == 429:
            retry_after = response.headers.get("Retry-After", "")
            try:
                retry_seconds = int(retry_after)
            except ValueError:
                try:
                    retry_at = parsedate_to_datetime(retry_after)
                    if retry_at.tzinfo is None:
                        retry_at = retry_at.replace(tzinfo=UTC)
                    retry_seconds = int((retry_at - datetime.now(UTC)).total_seconds())
                except (TypeError, ValueError, OverflowError):
                    retry_seconds = 60
            logger.warning("voyage_rate_limited", retry_after_seconds=max(retry_seconds, 1))
            raise VoyageRateLimitError(retry_seconds)
        response.raise_for_status()
        data = response.json().get("data", [])
        if len(data) != len(batch):
            raise RuntimeError("Voyage returned an unexpected embedding count")
        embeddings.extend(item["embedding"] for item in data)
    return embeddings


def _sparse_vectors(texts: list[str]) -> list[dict[str, list[Any]]]:
    """Encode text as FastEmbed sparse vectors."""
    vectors = []
    for offset in range(0, len(texts), 64):
        for item in _sparse_encoder().embed(texts[offset:offset + 64]):
            vectors.append({"indices": item.indices.tolist(), "values": item.values.tolist()})
    return vectors


def index_document(
    *, tenant_id: str, document_id: str, vendor_id: str | None, document_type: str,
    filename: str, artifact: dict[str, Any], vendor_name: str | None = None,
    created_at: datetime | None = None, source_version: str | None = None,
    collection: str | None = None,
) -> int:
    """Stage a complete generation before publishing and retiring older points.

    The caller must serialize indexing of the same document, including against
    deletion. A failed batch remains hidden, leaving the previous generation
    searchable. Legacy points without an index_state remain readable.
    """
    if not tenant_id.strip() or not document_id.strip():
        raise ValueError("tenant_id and document_id are required")
    settings = _rag_settings()
    collections = [collection or settings.qdrant_collection]
    mirror = getattr(settings, "qdrant_mirror_collection", "")
    if collection is None and mirror and mirror not in collections:
        collections.append(mirror)
    started = time.perf_counter()
    passages = build_passages(artifact, document_id=document_id)
    if not passages:
        raise ValueError("document extraction contains no indexable content")
    embedding_texts = [
        f"Document: {filename}\nVendor: {vendor_name or 'unknown'}\n"
        f"Type: {document_type}\nSection: {item.section or 'Unspecified'}\n\n{item.content}"
        for item in passages
    ]
    dense = _voyage_embeddings(embedding_texts, input_type="document")
    sparse = _sparse_vectors(embedding_texts)
    if len(dense) != len(passages) or len(sparse) != len(passages):
        raise RuntimeError("embedding count does not match document passages")
    for vector in dense:
        if len(vector) != _DENSE_SIZE or not all(math.isfinite(value) for value in vector):
            raise RuntimeError("embedding dimensions or values do not match the index")

    generation = str(uuid.uuid4())
    generation_namespace = uuid.UUID(generation)
    timestamp = None
    if created_at is not None:
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=UTC)
        timestamp = int(created_at.timestamp())
    common = {
        "tenant_id": tenant_id, "document_id": document_id, "vendor_id": vendor_id,
        "document_type": document_type, "filename": filename, "created_at_epoch": timestamp,
        "generation": generation, "index_state": "staged", "index_version": 3,
        "source_version": source_version,
    }
    points: list[dict[str, Any]] = []
    parents: set[str] = set()
    ordered_parents: list[dict[str, Any]] = []
    for passage, dense_vector, sparse_vector in zip(passages, dense, sparse, strict=True):
        parent_id = str(uuid.uuid5(generation_namespace, passage.parent_id))
        chunk_id = str(uuid.uuid5(generation_namespace, passage.point_id))
        if parent_id not in parents:
            parents.add(parent_id)
            parent_point = {
                "id": parent_id, "vector": {},
                "payload": {**common, "record_type": "parent", "parent_id": parent_id,
                            "page": passage.page, "section": passage.section,
                            "content": passage.parent_content},
            }
            points.append(parent_point)
            ordered_parents.append(parent_point)
        points.append({
            "id": chunk_id, "vector": {_DENSE_NAME: dense_vector, _SPARSE_NAME: sparse_vector},
            "payload": {**common, "record_type": "child", "chunk_id": chunk_id,
                        "parent_id": parent_id, "page": passage.page,
                        "section": passage.section, "content": passage.content,
                        "bbox": passage.bbox},
        })
    for left, right in itertools.pairwise(ordered_parents):
        previous, following = left["payload"], right["payload"]
        if (previous.get("section") and previous.get("section") == following.get("section")
                and isinstance(previous.get("page"), int)
                and following.get("page") == previous["page"] + 1):
            previous["next_parent_id"] = right["id"]
            following["previous_parent_id"] = left["id"]
    for point in points:
        point["payload"]["expected_children"] = len(passages)
        point["payload"]["expected_parents"] = len(parents)

    with httpx.Client(timeout=60) as client:
        headers = _qdrant_headers()
        aliases: dict[str, str] = {}
        if len(collections) > 1:
            alias_response = client.get(f"{_qdrant_url()}/aliases", headers=headers)
            alias_response.raise_for_status()
            aliases = {item["alias_name"]: item["collection_name"] for item in
                       (alias_response.json().get("result") or {}).get("aliases", [])}
        unique_collections: list[str] = []
        resolved: set[str] = set()
        for target in collections:
            actual = aliases.get(target, target)
            if actual not in resolved:
                resolved.add(actual)
                unique_collections.append(target)
        collections = unique_collections
        for target in collections:
            _ensure_collection(client, target)
            base = f"{_qdrant_url()}/collections/{target}/points"
            for offset in range(0, len(points), 64):
                response = client.put(
                    f"{base}?wait=true", headers=headers,
                    json={"points": points[offset:offset + 64]},
                )
                response.raise_for_status()
            scope = [
                {"key": "tenant_id", "match": {"value": tenant_id}},
                {"key": "document_id", "match": {"value": document_id}},
            ]
            response = client.post(
                f"{base}/payload?wait=true", headers=headers,
                json={"payload": {"index_state": "active"}, "filter": {"must": [
                    *scope, {"key": "generation", "match": {"value": generation}},
                ]}},
            )
            response.raise_for_status()
            response = client.post(
                f"{base}/delete?wait=true", headers=headers,
                json={"filter": {"must": scope, "must_not": [
                    {"key": "generation", "match": {"value": generation}},
                ]}},
            )
            response.raise_for_status()
    logger.info("rag_document_indexed", tenant_id=tenant_id, document_id=document_id,
                passage_count=len(passages), parent_count=len(parents),
                collection_count=len(collections),
                elapsed_ms=int((time.perf_counter() - started) * 1000))
    return len(passages)


def delete_document_points(
    *, tenant_id: str, document_id: str, collection: str | None = None,
) -> bool:
    """Delete every Qdrant point indexed for one document.

    Deletion is scoped by tenant and structured document id so a tenant can
    never remove another tenant's vectors. A missing collection is treated as
    a successful no-op because there is nothing left to retrieve.

    Args:
        tenant_id: Owning tenant.
        document_id: Structured ``documents.id`` used as the payload key.

    Returns:
        ``True`` when the delete request reached Qdrant, ``False`` when the
        collection does not exist.
    """
    settings = _rag_settings()
    collections = [collection or settings.qdrant_collection]
    mirror = getattr(settings, "qdrant_mirror_collection", "")
    if collection is None and mirror and mirror not in collections:
        collections.append(mirror)
    deleted = False
    with httpx.Client(timeout=20) as client:
        for collection in collections:
            response = client.post(
                f"{_qdrant_url()}/collections/{collection}/points/delete?wait=true",
                headers=_qdrant_headers(),
                json={"filter": {"must": [
                    {"key": "tenant_id", "match": {"value": tenant_id}},
                    {"key": "document_id", "match": {"value": document_id}},
                ]}},
            )
            if response.status_code == 404:
                continue
            response.raise_for_status()
            deleted = True
    logger.info("rag_document_points_deleted", tenant_id=tenant_id, document_id=document_id)
    return deleted


def _sparse_query(query: str) -> dict[str, list[Any]]:
    """Encode a single query into FastEmbed sparse form."""
    return _sparse_vectors([query])[0]


def hydrate_parent_passages(
    rows: list[dict[str, Any]], *, tenant_id: str, collection: str | None = None,
) -> list[dict[str, Any]]:
    """Load parents only for selected children, enforcing tenant and document identity."""
    parent_ids = list(dict.fromkeys(
        str(row["parent_id"]) for row in rows
        if row.get("record_type") == "child" and row.get("parent_id")
    ))
    if not parent_ids:
        return rows
    collection = collection or _rag_settings().qdrant_collection
    parents: dict[str, dict[str, Any]] = {}
    with httpx.Client(timeout=30) as client:
        def load_parents(ids_to_load: list[str]) -> None:
            """Fetch a bounded set of tenant-scoped parent points."""
            for offset in range(0, len(ids_to_load), 100):
                ids = ids_to_load[offset:offset + 100]
                response = client.post(
                    f"{_qdrant_url()}/collections/{collection}/points/scroll",
                    headers=_qdrant_headers(),
                    json={"filter": {"must": [
                        {"key": "tenant_id", "match": {"value": tenant_id}},
                        {"key": "record_type", "match": {"value": "parent"}},
                        {"has_id": ids},
                    ], "must_not": [{"key": "index_state", "match": {"value": "staged"}}]},
                        "limit": len(ids), "with_payload": True, "with_vector": False},
                )
                response.raise_for_status()
                for point in (response.json().get("result") or {}).get("points", []):
                    parents[str(point.get("id"))] = point.get("payload") or {}

        load_parents(parent_ids)
        adjacent_ids = list(dict.fromkeys(
            str(parent[key]) for parent in parents.values()
            for key in ("previous_parent_id", "next_parent_id") if parent.get(key)
        ))
        load_parents([item for item in adjacent_ids if item not in parents])
    for row in rows:
        if row.get("record_type") != "child":
            continue  # Legacy children already contain parent_content.
        parent = parents.get(str(row.get("parent_id")))
        if (parent and parent.get("tenant_id") == tenant_id
                and parent.get("document_id") == row.get("document_id")
                and parent.get("generation") == row.get("generation")
                and parent.get("page") == row.get("page")):
            row["parent_content"] = parent.get("content") or row.get("content")
            adjacent = []
            for key in ("previous_parent_id", "next_parent_id"):
                neighbor_id = parent.get(key)
                neighbor = parents.get(str(neighbor_id))
                if (neighbor and neighbor.get("tenant_id") == tenant_id
                        and neighbor.get("document_id") == row.get("document_id")
                        and neighbor.get("generation") == row.get("generation")
                        and neighbor.get("section") == row.get("section")
                        and isinstance(neighbor.get("page"), int)
                        and isinstance(row.get("page"), int)
                        and abs(neighbor["page"] - row["page"]) == 1):
                    adjacent.append({"parent_id": str(neighbor_id), "page": neighbor["page"],
                                     "section": neighbor.get("section"),
                                     "content": neighbor.get("content") or ""})
            if adjacent:
                row["adjacent_context"] = adjacent
        else:
            logger.warning("rag_parent_missing", tenant_id=tenant_id,
                           document_id=row.get("document_id"))
            row["parent_content"] = row.get("content")
    return rows


async def retain_existing_documents(
    session: Any, *, tenant_id: str, rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Fail closed on deleted or cross-tenant documents while cleanup is pending."""
    from sqlalchemy import select

    from zellovest_shared.db.transact import Document

    document_ids: set[uuid.UUID] = set()
    for row in rows:
        try:
            document_ids.add(uuid.UUID(str(row.get("document_id"))))
        except (ValueError, TypeError, AttributeError):
            continue
    if not document_ids:
        return []
    result = await session.scalars(select(Document.id).where(
        Document.tenant_id == tenant_id, Document.id.in_(document_ids),
    ))
    allowed = {str(item) for item in result.all()}
    return [row for row in rows if str(row.get("document_id")) in allowed]


def retain_existing_documents_sync(
    session: Any, *, tenant_id: str, rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Apply the same deletion guard for the legacy synchronous MCP server."""
    from sqlalchemy import select

    from zellovest_shared.db.transact import Document

    document_ids: set[uuid.UUID] = set()
    for row in rows:
        try:
            document_ids.add(uuid.UUID(str(row.get("document_id"))))
        except (ValueError, TypeError, AttributeError):
            continue
    if not document_ids:
        return []
    result = session.scalars(select(Document.id).where(
        Document.tenant_id == tenant_id, Document.id.in_(document_ids),
    ))
    allowed = {str(item) for item in result.all()}
    return [row for row in rows if str(row.get("document_id")) in allowed]


def _rerank(query: str, rows: list[dict[str, Any]], *, model: str) -> list[dict[str, Any]]:
    """Rerank bounded child candidates with the configured Voyage reranker."""
    settings = _rag_settings()
    if not settings.voyage_api_key:
        raise RuntimeError("VOYAGE_API_KEY is required for reranking")
    response = httpx.post(
        settings.rag_rerank_url,
        headers={"Authorization": f"Bearer {settings.voyage_api_key}"},
        json={"model": model, "query": query,
              "documents": [str(row.get("content") or "") for row in rows],
              "return_documents": False}, timeout=20,
    )
    response.raise_for_status()
    data = response.json().get("data", [])
    indices = [item.get("index") for item in data]
    if (len(indices) != len(rows) or set(indices) != set(range(len(rows)))
            or any(not math.isfinite(float(item.get("relevance_score", float("nan"))))
                   for item in data)):
        raise RuntimeError("reranker returned incomplete or invalid rankings")
    return [{**rows[item["index"]], "rerank_score": float(item["relevance_score"])}
            for item in data]


def search_documents(
    *, tenant_id: str, query: str, vendor_id: str | None = None,
    document_type: str | None = None, document_id: str | None = None,
    document_types: Sequence[str] | None = None, limit: int = 10,
    technique: str | None = None, fail_on_missing_collection: bool = False,
    document_ids: Sequence[str] | None = None, collection: str | None = None,
) -> list[dict[str, Any]]:
    """Search Qdrant with dense and sparse retrieval, then fuse ranks with RRF.

    Args:
        tenant_id: Owning tenant; always applied as a hard Qdrant filter.
        query: Natural-language search query.
        vendor_id: Optional vendor filter.
        document_type: Optional single document-type filter.
        document_id: Optional structured document id filter.
        document_types: Optional set of document types (for contract +
            amendment searches). Ignored when ``document_type`` is set.
        limit: Maximum number of child passages to return.
        technique: Dense, sparse, or hybrid retrieval.
        fail_on_missing_collection: Reject a missing index instead of returning no results.

    Returns:
        Payload dictionaries enriched with the fused relevance score.
    """
    started = time.perf_counter()
    settings = _rag_settings()
    rerank_model = getattr(settings, "rag_rerank_model", "")
    technique = technique or ("hybrid_rerank" if rerank_model else "hybrid")
    if technique not in {"dense", "sparse", "hybrid", "hybrid_rerank"}:
        raise ValueError("unsupported retrieval technique")
    if not tenant_id or not query.strip() or not 1 <= limit <= 200:
        raise ValueError("tenant, query, and a valid limit are required")
    if document_ids is not None and not document_ids:
        return []
    allowed_document_ids = set(document_ids) if document_ids is not None else None
    if technique == "hybrid_rerank" and not rerank_model:
        raise ValueError("RAG_RERANK_MODEL is required for reranking")
    collection = collection or settings.qdrant_collection
    must: list[dict[str, Any]] = [{"key": "tenant_id", "match": {"value": tenant_id}}]
    if vendor_id:
        must.append({"key": "vendor_id", "match": {"value": vendor_id}})
    if document_id:
        must.append({"key": "document_id", "match": {"value": document_id}})
    if document_ids is not None:
        must.append({"key": "document_id", "match": {"any": list(document_ids)}})
    if document_type:
        must.append({"key": "document_type", "match": {"value": document_type}})
    elif document_types:
        must.append({"key": "document_type", "match": {"any": list(document_types)}})
    query_filter = {"must": must, "must_not": [
        {"key": "index_state", "match": {"value": "staged"}},
        {"key": "record_type", "match": {"value": "parent"}},
    ]}
    dense = _voyage_embeddings([query], input_type="query")[0] if technique != "sparse" else None
    sparse = _sparse_query(query) if technique != "dense" else None
    with httpx.Client(timeout=30) as client:
        headers = _qdrant_headers()
        base = f"{_qdrant_url()}/collections/{collection}/points/query"
        candidate_limit = min(200, max(limit * 4, 20))
        if technique in {"hybrid", "hybrid_rerank"}:
            request_body = {"prefetch": [
                {"query": dense, "using": _DENSE_NAME, "filter": query_filter,
                 "limit": candidate_limit * 3},
                {"query": sparse, "using": _SPARSE_NAME, "filter": query_filter,
                 "limit": candidate_limit * 3},
            ], "query": {"fusion": "rrf"}, "filter": query_filter,
                "limit": candidate_limit, "with_payload": True}
        else:
            request_body = {"query": dense if technique == "dense" else sparse,
                            "using": _DENSE_NAME if technique == "dense" else _SPARSE_NAME,
                            "filter": query_filter, "limit": candidate_limit, "with_payload": True}
        response = client.post(base, headers=headers, json=request_body)
        if response.status_code == 404:
            if fail_on_missing_collection:
                raise RuntimeError("Qdrant collection does not exist")
            return []
        response.raise_for_status()
        points = (response.json().get("result") or {}).get("points", [])
    rows = []
    for point in points:
        payload = point.get("payload") or {}
        if (payload.get("tenant_id") != tenant_id
                or payload.get("index_state") == "staged"
                or payload.get("record_type") == "parent"
                or (vendor_id and payload.get("vendor_id") != vendor_id)
                or (document_id and payload.get("document_id") != document_id)
                or (allowed_document_ids is not None
                    and payload.get("document_id") not in allowed_document_ids)
                or (document_type and payload.get("document_type") != document_type)
                or (not document_type and document_types
                    and payload.get("document_type") not in document_types)):
            logger.warning("rag_filtered_result_rejected", tenant_id=tenant_id)
            continue
        rows.append({**payload, "score": float(point.get("score", 0.0))})
    if technique == "hybrid_rerank" and rows:
        try:
            rows = _rerank(query, rows, model=rerank_model)
        except Exception as exc:
            logger.warning("rag_rerank_failed", tenant_id=tenant_id,
                           error_class=type(exc).__name__)
            if fail_on_missing_collection:
                raise
    # Keep one strongest hit per parent to avoid consuming the context with
    # overlapping siblings. Retain legacy rows without a parent independently.
    unique: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    seen_text: set[tuple[str, str, str, str]] = set()
    for row in rows:
        key = (str(row.get("document_id") or ""),
               str(row.get("parent_id") or row.get("chunk_id") or ""))
        text_key = (str(row.get("document_id") or ""), str(row.get("page") or ""),
                    str(row.get("section") or ""),
                    re.sub(r"\s+", " ", str(row.get("content") or "")).strip())
        if key not in seen and text_key not in seen_text:
            unique.append(row)
            seen.add(key)
            seen_text.add(text_key)
        if len(unique) >= limit:
            break
    hydrate_parent_passages(unique, tenant_id=tenant_id, collection=collection)
    logger.info("rag_search_completed", tenant_id=tenant_id, technique=technique,
                candidate_count=len(rows), result_count=len(unique),
                elapsed_ms=int((time.perf_counter() - started) * 1000))
    return unique


def sample_indexed_contexts(
    *, tenant_id: str, limit: int = 10, vendor_id: str | None = None
) -> list[dict[str, Any]]:
    """Fetch a bounded, deduplicated set of indexed parent passages for evaluation."""
    collection = _rag_settings().qdrant_collection
    url = f"{_qdrant_url()}/collections/{collection}/points/scroll"
    must = [
        {"key": "tenant_id", "match": {"value": tenant_id}},
        {"key": "document_type", "match": {"any": ["contract", "amendment"]}},
    ]
    if vendor_id:
        must.append({"key": "vendor_id", "match": {"value": vendor_id}})
    with httpx.Client(timeout=20) as client:
        response = client.post(url, headers=_qdrant_headers(), json={
            "filter": {"must": must, "must_not": [
                {"key": "index_state", "match": {"value": "staged"}},
                {"key": "record_type", "match": {"value": "parent"}},
            ]},
            "limit": min(100, limit * 10), "with_payload": True, "with_vector": False,
        })
        if response.status_code == 404:
            return []
        response.raise_for_status()
    contexts: dict[str, dict[str, Any]] = {}
    for point in (response.json().get("result") or {}).get("points", []):
        payload = point.get("payload") or {}
        parent_id = str(payload.get("parent_id") or point.get("id"))
        contexts.setdefault(parent_id, payload)
    return hydrate_parent_passages(list(contexts.values())[:limit], tenant_id=tenant_id)
