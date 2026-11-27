"""Regression tests for section chunking and labeled retrieval metrics."""

import pytest
from zellovest_shared.rag import _paragraphs, build_passages
from zellovest_shared.rag_benchmark import benchmark_retrieval


def test_parents_keep_children_on_their_source_pages() -> None:
    """Larger parents preserve the page attached to each child citation."""
    artifact = {"extraction": {"pages": [
        {"page_number": 1, "text": "RENEWAL\n" + "notice period applies. " * 35},
        {"page_number": 2, "text": "Written notice is required before renewal."},
    ]}}
    passages = build_passages(artifact, document_id="doc")
    assert len(passages) > 2
    assert len({item.parent_id for item in passages}) == 2
    assert {item.page for item in passages} == {1, 2}
    assert all(len(item.content) < len(item.parent_content)
               for item in passages if item.page == 1)
    assert all(item.bbox is None for item in passages)
    assert passages == build_passages(artifact, document_id="doc")


def test_table_rows_keep_headers_and_real_bbox() -> None:
    """Rows can be retrieved with their headers and actual table location."""
    artifact = {"extraction": {"pages": [{"page_number": 1, "text": "",
        "tables": [{"data": [["Product", "Price"], ["Seat", "$12"]],
                    "bbox": [1, 2, 3, 4]}]}]}}
    passage = build_passages(artifact, document_id="doc")[0]
    assert "Product | Price" in passage.content
    assert "Seat | $12" in passage.content
    assert passage.bbox == [1, 2, 3, 4]


def test_long_paragraph_does_not_reorder_earlier_content() -> None:
    """A long paragraph must not be emitted ahead of a preceding paragraph."""
    result = _paragraphs("first\n\n" + "later " * 200)
    assert result[0] == "first"


def test_benchmark_uses_unique_document_labels_and_paired_queries() -> None:
    """Duplicate chunks do not inflate document recall or ranking metrics."""
    def retrieve(**kwargs):
        """Return controlled rankings for each retrieval technique."""
        ids = ["a", "a", "b"] if kwargs["technique"] == "hybrid" else ["x", "b"]
        return [{"document_id": item} for item in ids]

    cases = [{"query": "renewal", "relevant_document_ids": ["a", "b"]}]
    result = benchmark_retrieval(cases, retrieve, tenant_id="t", k=3)
    assert result["techniques"]["hybrid"]["recall_at_k"] == 1
    assert result["techniques"]["hybrid"]["mrr_at_k"] == 1
    assert result["techniques"]["dense"]["recall_at_k"] == 0.5
    assert result["techniques"]["dense"]["mrr_at_k"] == 0.5
    with pytest.raises(ValueError):
        benchmark_retrieval([{"query": "q", "relevant_document_ids": []}], retrieve,
                            tenant_id="t")


def test_page_labels_measure_the_evidence_page() -> None:
    """Finding the right document on the wrong page does not score as a page hit."""
    def retrieve(**kwargs):
        """Return the correct document on a different page."""
        return [{"document_id": "a", "page": 2}]

    cases = [{"query": "notice", "relevant_document_ids": ["a"],
              "relevant_pages": [{"document_id": "a", "page": 7}]}]
    scores = benchmark_retrieval(cases, retrieve, tenant_id="t")["techniques"]["hybrid"]
    assert scores["recall_at_k"] == 1
    assert scores["page_recall_at_k"] == 0
    assert scores["page_mrr_at_k"] == 0
