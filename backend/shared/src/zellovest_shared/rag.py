"""Document chunking, Voyage embeddings, FastEmbed sparse vectors, and Qdrant IO."""

from __future__ import annotations

import hashlib
import re
import uuid
from dataclasses import dataclass
from typing import Any

import httpx

from zellovest_shared.logging_conf import get_logger

logger = get_logger(__name__)
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
    parts = [re.sub(r"\s+", " ", part).strip() for part in re.split(r"\n\s*\n", text)]
    parts = [part for part in parts if part]
    chunks: list[str] = []
    current = ""
    for part in parts:
        while len(part) > max_chars:
            cut = part.rfind(" ", 0, max_chars)
            cut = cut if cut > max_chars // 2 else max_chars
            chunks.append(part[:cut].strip())
            part = part[max(0, cut - overlap_chars):].strip()
        candidate = f"{current}\n{part}" if current else part
        if len(candidate) > max_chars and current:
            chunks.append(current)
            current = f"{current[-overlap_chars:]} {part}".strip()
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


def build_passages(artifact: dict[str, Any], *, document_id: str) -> list[Passage]:
    """Build stable, page-aware passages from the stored extraction artifact."""
    extraction = artifact.get("extraction") or {}
    pages = extraction.get("pages") or []
    if not pages and extraction.get("full_text"):
        pages = [{"page_number": 1, "text": extraction["full_text"]}]
    passages: list[Passage] = []
    for page_data in pages:
        page = int(page_data.get("page_number") or 1)
        text = str(page_data.get("text") or "")
        table_text = []
        for table in page_data.get("tables") or []:
            rows = table.get("data") or []
            table_text.append("\n".join(" | ".join(str(cell) for cell in row) for row in rows))
        if table_text:
            text = f"{text}\n\n" + "\n\n".join(table_text)
        if not text.strip():
            continue
        blocks = page_data.get("text_blocks") or []
        bbox = blocks[0].get("bbox") if blocks else None
        headings = re.compile(r"(?m)^\s*((?:\d+(?:\.\d+)*[.)]?\s+)?[A-Z][A-Z\d ,/&()'’-]{3,90})\s*$")
        matches = list(headings.finditer(text))
        sections: list[tuple[str | None, str]] = []
        if matches:
            cursor = 0
            active = None
            for match in matches:
                if match.start() > cursor:
                    sections.append((active, text[cursor:match.start()].strip()))
                active = match.group(1).strip()
                cursor = match.end()
            sections.append((active, text[cursor:].strip()))
        else:
            sections = [(None, text)]
        for section, parent_text in sections:
            if not parent_text:
                continue
            parent_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{document_id}:{page}:{section}:{parent_text}"))
            for index, content in enumerate(_paragraphs(parent_text)):
                digest = hashlib.sha1(content.encode("utf-8")).hexdigest()[:12]
                point_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{parent_id}:{index}:{digest}"))
                passages.append(Passage(point_id, parent_id, content, parent_text, page, section, bbox))
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
        response.raise_for_status()
    for field_name in ("tenant_id", "vendor_id", "document_type", "document_id"):
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
    filename: str, artifact: dict[str, Any],
) -> int:
    """Replace a document's Qdrant points with freshly chunked and embedded passages."""
    collection = _rag_settings().qdrant_collection
    passages = build_passages(artifact, document_id=document_id)
    if not passages:
        logger.warning("rag_document_empty", tenant_id=tenant_id, document_id=document_id)
        return 0
    embedding_texts = [
        f"Document: {filename}\nVendor: {vendor_id or 'unknown'}\n"
        f"Type: {document_type}\nSection: {item.section or 'Unspecified'}\n\n{item.content}"
        for item in passages
    ]
    dense = _voyage_embeddings(embedding_texts, input_type="document")
    sparse = _sparse_vectors(embedding_texts)
    with httpx.Client(timeout=60) as client:
        _ensure_collection(client, collection)
        headers = _qdrant_headers()
        delete_response = client.post(
            f"{_qdrant_url()}/collections/{collection}/points/delete?wait=true",
            headers=headers,
            json={"filter": {"must": [
                {"key": "tenant_id", "match": {"value": tenant_id}},
                {"key": "document_id", "match": {"value": document_id}},
            ]}},
        )
        delete_response.raise_for_status()
        points = []
        for passage, dense_vector, sparse_vector in zip(passages, dense, sparse, strict=True):
            points.append({
                "id": passage.point_id,
                "vector": {_DENSE_NAME: dense_vector,
                           _SPARSE_NAME: sparse_vector},
                "payload": {
                    "tenant_id": tenant_id, "document_id": document_id,
                    "vendor_id": vendor_id, "document_type": document_type,
                    "filename": filename, "chunk_id": passage.point_id,
                    "parent_id": passage.parent_id, "page": passage.page,
                    "section": passage.section, "content": passage.content,
                    "parent_content": passage.parent_content, "bbox": passage.bbox,
                },
            })
        for offset in range(0, len(points), 64):
            response = client.put(
                f"{_qdrant_url()}/collections/{collection}/points?wait=true",
                headers=headers, json={"points": points[offset:offset + 64]},
            )
            response.raise_for_status()
    logger.info("rag_document_indexed", tenant_id=tenant_id, document_id=document_id,
                passage_count=len(passages))
    return len(passages)


def delete_document_points(*, tenant_id: str, document_id: str) -> bool:
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
    collection = _rag_settings().qdrant_collection
    with httpx.Client(timeout=20) as client:
        response = client.post(
            f"{_qdrant_url()}/collections/{collection}/points/delete?wait=true",
            headers=_qdrant_headers(),
            json={"filter": {"must": [
                {"key": "tenant_id", "match": {"value": tenant_id}},
                {"key": "document_id", "match": {"value": document_id}},
            ]}},
        )
        if response.status_code == 404:
            logger.info(
                "rag_document_delete_collection_missing",
                tenant_id=tenant_id,
                document_id=document_id,
            )
            return False
        response.raise_for_status()
    logger.info("rag_document_points_deleted", tenant_id=tenant_id, document_id=document_id)
    return True


def _sparse_query(query: str) -> dict[str, list[Any]]:
    """Encode a single query into FastEmbed sparse form."""
    return _sparse_vectors([query])[0]


def search_documents(
    *, tenant_id: str, query: str, vendor_id: str | None = None,
    document_type: str | None = None, limit: int = 10,
) -> list[dict[str, Any]]:
    """Search Qdrant with dense and sparse retrieval, then fuse ranks with RRF."""
    collection = _rag_settings().qdrant_collection
    must: list[dict[str, Any]] = [{"key": "tenant_id", "match": {"value": tenant_id}}]
    if vendor_id:
        must.append({"key": "vendor_id", "match": {"value": vendor_id}})
    if document_type:
        must.append({"key": "document_type", "match": {"value": document_type}})
    query_filter = {"must": must}
    dense = _voyage_embeddings([query], input_type="query")[0]
    sparse = _sparse_query(query)
    with httpx.Client(timeout=30) as client:
        headers = _qdrant_headers()
        base = f"{_qdrant_url()}/collections/{collection}/points/query"
        response = client.post(base, headers=headers, json={
            "prefetch": [
                {"query": dense, "using": _DENSE_NAME, "filter": query_filter,
                 "limit": limit * 3},
                {"query": sparse, "using": _SPARSE_NAME, "filter": query_filter,
                 "limit": limit * 3},
            ],
            "query": {"fusion": "rrf"}, "limit": limit, "with_payload": True,
        })
        if response.status_code == 404:
            return []
        response.raise_for_status()
        points = (response.json().get("result") or {}).get("points", [])
    return [{**(point.get("payload") or {}), "score": float(point.get("score", 0.0))}
            for point in points]


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
            "filter": {"must": must},
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
    return list(contexts.values())[:limit]
