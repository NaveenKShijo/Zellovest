"""Optional integration test against an isolated local Qdrant process."""

from __future__ import annotations

import os
import uuid
from types import SimpleNamespace
from urllib.parse import urlparse

import httpx
import pytest
from zellovest_shared import rag
from zellovest_shared.rag_benchmark import benchmark_retrieval

import rag_reindex


def test_real_qdrant_parent_child_lifecycle(monkeypatch: pytest.MonkeyPatch) -> None:
    """Publish, query, replace, and delete without crossing tenant boundaries."""
    url = os.getenv("RAG_TEST_QDRANT_URL", "").rstrip("/")
    if not url:
        pytest.skip("set RAG_TEST_QDRANT_URL to an isolated local test instance")
    parsed = urlparse(url)
    if parsed.hostname not in {"127.0.0.1", "localhost"} or parsed.port in {None, 6333}:
        pytest.fail("integration tests require an isolated local non-default Qdrant port")
    collection = f"rag_test_{uuid.uuid4().hex}"
    mirror = f"{collection}_mirror"
    settings = SimpleNamespace(qdrant_url=url, qdrant_api_key="", qdrant_collection=collection,
                               qdrant_mirror_collection=mirror, rag_rerank_model="")
    monkeypatch.setattr(rag, "_rag_settings", lambda: settings)
    monkeypatch.setattr(rag_reindex, "get_settings", lambda: settings)
    monkeypatch.setattr(rag, "_voyage_embeddings",
                        lambda texts, input_type: [[1.0] + [0.0] * 1023 for _ in texts])
    monkeypatch.setattr(rag, "_sparse_vectors",
                        lambda texts: [{"indices": [1], "values": [1.0]} for _ in texts])
    artifact = {"extraction": {"pages": [
        {"page_number": 2, "text": "RENEWAL\n" + "A thirty day notice is required. " * 30},
        {"page_number": 3, "text": "The renewal continues annually. " * 30},
    ]}}
    try:
        rag.index_document(tenant_id="tenant-a", document_id="doc-a", vendor_id="vendor-a",
                           document_type="contract", filename="a.pdf", artifact=artifact,
                           source_version="v1")
        rag.index_document(tenant_id="tenant-b", document_id="doc-b", vendor_id="vendor-b",
                           document_type="contract", filename="b.pdf", artifact=artifact)
        assert rag.search_documents(tenant_id="tenant-a", query="notice", collection=mirror)
        staged = {"id": str(uuid.uuid4()), "vector": {
            "dense": [1.0] + [0.0] * 1023, "sparse": {"indices": [1], "values": [1.0]}},
            "payload": {"tenant_id": "tenant-a", "document_id": "doc-a",
                        "record_type": "child", "index_state": "staged", "content": "hidden"}}
        httpx.put(f"{url}/collections/{collection}/points?wait=true", json={"points": [staged]},
                  timeout=20).raise_for_status()
        status = rag_reindex.target_status("tenant-a", collection)
        assert not any(rag_reindex.compare_index({"doc-a": "v1"}, status).values())
        for technique in ("dense", "sparse", "hybrid"):
            rows = rag.search_documents(tenant_id="tenant-a", query="notice",
                                        technique=technique, limit=5)
            assert rows and {row["document_id"] for row in rows} == {"doc-a"}
            assert {row["page"] for row in rows} == {2, 3}
            assert all(row["content"] != "hidden" for row in rows)
            assert all(len(row["parent_content"]) > len(row["content"]) for row in rows)
            assert all(row["adjacent_context"][0]["page"] == (3 if row["page"] == 2 else 2)
                       for row in rows)
        report = benchmark_retrieval(
            [{"query": "notice", "relevant_document_ids": ["doc-a"],
              "relevant_pages": [{"document_id": "doc-a", "page": 2}]}],
            rag.search_documents, tenant_id="tenant-a", k=5,
        )
        assert all(score["recall_at_k"] == 1 and score["page_recall_at_k"] == 1
                   for score in report["techniques"].values())
        assert not rag.search_documents(tenant_id="tenant-a", query="notice",
                                        vendor_id="vendor-b", limit=5)
        replacement = {"extraction": {"pages": [{"page_number": 1,
                       "text": "Updated cancellation clause."}]}}
        rag.index_document(tenant_id="tenant-a", document_id="doc-a", vendor_id="vendor-a",
                           document_type="contract", filename="a.pdf", artifact=replacement)
        rows = rag.search_documents(tenant_id="tenant-a", query="notice", limit=5)
        assert len(rows) == 1 and rows[0]["content"] == "Updated cancellation clause."
        rag.delete_document_points(tenant_id="tenant-a", document_id="doc-a")
        assert not rag.search_documents(tenant_id="tenant-a", query="notice", limit=5)
        assert not rag.search_documents(tenant_id="tenant-a", query="notice", collection=mirror)
        assert rag.search_documents(tenant_id="tenant-b", query="notice", limit=5)
    finally:
        for target in (collection, mirror):
            response = httpx.delete(f"{url}/collections/{target}", timeout=20)
            if response.status_code != 404:
                response.raise_for_status()
