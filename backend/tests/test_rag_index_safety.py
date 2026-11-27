"""Exercise index publication, retrieval filters, and source provenance."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Self

import pytest
from zellovest_shared import rag


class Response:
    """Small Qdrant response stub."""

    status_code = 200

    def __init__(self, result: dict[str, Any] | None = None) -> None:
        """Store the result payload."""
        self.result = result or {}

    def raise_for_status(self) -> None:
        """Allow successful fake requests."""

    def json(self) -> dict[str, Any]:
        """Return the Qdrant response envelope."""
        return {"result": self.result}


class QdrantStub:
    """Record writes and provide controlled query/parent responses."""

    def __init__(self) -> None:
        """Initialize recorded operations and optional failures."""
        self.writes: list[tuple[str, str, dict[str, Any]]] = []
        self.fail_batch = False
        self.batches = 0
        self.query_points: list[dict[str, Any]] = []
        self.parent_points: list[dict[str, Any]] = []

    def __call__(self, **kwargs: Any) -> QdrantStub:
        """Act as an httpx.Client factory."""
        return self

    def __enter__(self) -> Self:
        """Enter the fake client context."""
        return self

    def __exit__(self, *args: object) -> None:
        """Exit the fake client context."""

    def get(self, url: str, **kwargs: Any) -> Response:
        """Resolve the active alias to the mirror's physical collection."""
        return Response({"aliases": [{"alias_name": "active", "collection_name": "physical"}]})

    def put(self, url: str, **kwargs: Any) -> Response:
        """Record upsert batches and optionally fail the second batch."""
        self.batches += 1
        self.writes.append(("put", url, kwargs["json"]))
        if self.fail_batch and self.batches == 2:
            raise RuntimeError("simulated failed write")
        return Response()

    def post(self, url: str, **kwargs: Any) -> Response:
        """Record publication and return controlled search results."""
        body = kwargs["json"]
        self.writes.append(("post", url, body))
        if url.endswith("/points/query"):
            return Response({"points": self.query_points})
        if url.endswith("/points/scroll"):
            return Response({"points": self.parent_points})
        return Response()


@pytest.fixture
def qdrant(monkeypatch: pytest.MonkeyPatch) -> QdrantStub:
    """Replace network and embedding calls with deterministic stubs."""
    settings = SimpleNamespace(
        qdrant_url="http://qdrant", qdrant_api_key="", qdrant_collection="active",
        qdrant_mirror_collection="physical", rag_rerank_model="",
    )
    stub = QdrantStub()
    monkeypatch.setattr(rag, "_rag_settings", lambda: settings)
    monkeypatch.setattr(rag.httpx, "Client", stub)
    monkeypatch.setattr(rag, "_ensure_collection", lambda client, collection: None)
    monkeypatch.setattr(rag, "_voyage_embeddings",
                        lambda texts, input_type: [[0.1] * 1024 for _ in texts])
    monkeypatch.setattr(rag, "_sparse_vectors",
                        lambda texts: [{"indices": [1], "values": [1.0]} for _ in texts])
    return stub


def passages(count: int) -> list[rag.Passage]:
    """Create multiple unique children of one bounded parent."""
    return [rag.Passage(str(number), "parent", f"child {number}", "larger context", 1,
                        "RENEWAL", None) for number in range(count)]


def test_incomplete_generation_is_never_published_or_deleted(
    qdrant: QdrantStub, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed batch cannot remove the previous searchable generation."""
    monkeypatch.setattr(rag, "build_passages", lambda *args, **kwargs: passages(70))
    qdrant.fail_batch = True
    with pytest.raises(RuntimeError, match="simulated failed write"):
        rag.index_document(tenant_id="tenant-a", document_id="doc", vendor_id=None,
                           document_type="contract", filename="a.pdf", artifact={})
    assert qdrant.batches == 2
    assert all(op == "put" for op, _, _ in qdrant.writes)
    assert all(point["payload"]["index_state"] == "staged"
               for _, _, body in qdrant.writes for point in body["points"])


def test_publish_occurs_after_all_batches_and_before_retiring_old_generation(
    qdrant: QdrantStub, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Mirror aliases do not trigger a second write to the same collection."""
    monkeypatch.setattr(rag, "build_passages", lambda *args, **kwargs: passages(70))
    assert rag.index_document(tenant_id="tenant-a", document_id="doc", vendor_id=None,
                              document_type="contract", filename="a.pdf", artifact={}) == 70
    assert [entry[0] for entry in qdrant.writes] == ["put", "put", "post", "post"]
    assert "/payload?" in qdrant.writes[-2][1]
    assert "/delete?" in qdrant.writes[-1][1]
    scope = qdrant.writes[-1][2]["filter"]
    assert {"key": "tenant_id", "match": {"value": "tenant-a"}} in scope["must"]
    assert {"key": "document_id", "match": {"value": "doc"}} in scope["must"]
    parent = qdrant.writes[0][2]["points"][0]
    assert parent["payload"]["record_type"] == "parent" and parent["vector"] == {}
    assert parent["payload"]["expected_children"] == 70


def test_search_filters_both_branches_and_rejects_mismatched_parent(qdrant: QdrantStub) -> None:
    """Parent lookup cannot attach data from another tenant or document."""
    child = {"tenant_id": "tenant-a", "document_id": "doc", "record_type": "child",
             "index_state": "active", "generation": "gen", "parent_id": "parent",
             "chunk_id": "child", "content": "matched text", "page": 2,
             "vendor_id": "vendor"}
    qdrant.query_points = [{"payload": child, "score": 0.5}]
    qdrant.parent_points = [{"id": "parent", "payload": {
        "tenant_id": "tenant-b", "document_id": "doc", "generation": "gen", "page": 2,
        "content": "other tenant secret",
    }}]
    rows = rag.search_documents(tenant_id="tenant-a", query="renewal", document_ids=["doc"],
                                vendor_id="vendor", limit=3)
    assert rows[0]["parent_content"] == "matched text"
    query = next(body for _, url, body in qdrant.writes if url.endswith("/points/query"))
    assert query["prefetch"][0]["filter"] == query["prefetch"][1]["filter"] == query["filter"]
    assert {"key": "tenant_id", "match": {"value": "tenant-a"}} in query["filter"]["must"]
    assert {"key": "document_id", "match": {"any": ["doc"]}} in query["filter"]["must"]
    scroll = next(body for _, url, body in qdrant.writes if url.endswith("/points/scroll"))
    assert {"key": "tenant_id", "match": {"value": "tenant-a"}} in scroll["filter"]["must"]


def test_layout_deduplicates_table_blocks_and_repeats_headers() -> None:
    """Table fragments retain headers and table text is not indexed twice."""
    row = "item " * 200
    artifact = {"extraction": {"pages": [{
        "page_number": 1, "text": "Intro\nProduct Price\n" + row,
        "text_blocks": [{"text": "Intro", "bbox": [0, 0, 100, 10]},
                        {"text": "Product Price\n" + row, "bbox": [0, 20, 100, 100]}],
        "tables": [{"bbox": [0, 20, 100, 100],
                    "data": [["Product", "Price"], [row, "100"]]}],
    }]}}
    result = rag.build_passages(artifact, document_id="doc")
    table_children = [item for item in result if item.bbox == [0, 20, 100, 100]]
    assert len(table_children) > 1
    assert all(item.content.startswith("Product | Price") for item in table_children)
    assert any(item.content == "Intro" for item in result)


def test_zero_overlap_keeps_parents_bounded() -> None:
    """A zero-overlap split does not accidentally repeat an entire paragraph."""
    pieces = rag._paragraphs("a" * 60 + "\n\n" + "b" * 60, max_chars=100, overlap_chars=0)
    assert pieces == ["a" * 60, "b" * 60]


def test_vector_cleanup_failure_is_not_reported_as_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The cleanup task fails so Celery can retry a transient Qdrant outage."""
    from zellovest_shared import config
    from zellovest_workers.tasks.maintenance import purge_document_artifacts

    monkeypatch.setattr(config, "get_settings", lambda: SimpleNamespace(gcs_raw_bucket=""))

    def fail_delete(**kwargs: Any) -> None:
        """Simulate an unavailable vector store."""
        raise RuntimeError("Qdrant unavailable")

    monkeypatch.setattr(rag, "delete_document_points", fail_delete)
    with pytest.raises(RuntimeError, match="cleanup incomplete"):
        purge_document_artifacts("tenant-a", "upload", [], ["doc"])
