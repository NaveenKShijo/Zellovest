"""Measure retrieval against a fixed set of human-labeled source documents."""

from __future__ import annotations

import math
import statistics
import time
from collections.abc import Callable, Sequence
from typing import Any


def benchmark_retrieval(
    cases: Sequence[dict[str, Any]],
    retrieve: Callable[..., list[dict[str, Any]]],
    *,
    tenant_id: str,
    k: int = 10,
    techniques: Sequence[str] = ("dense", "sparse", "hybrid"),
) -> dict[str, Any]:
    """Compare ranked results using document-level labels and paired queries.

    Each case requires a query and at least one relevant document ID. Labels are
    deliberately document-level so they survive changes in chunk boundaries.
    Failed queries abort the run instead of being counted as zero relevance.
    """
    if not cases or not techniques or not 1 <= k <= 50:
        raise ValueError("supply at least one case and a k between 1 and 50")
    for case in cases:
        if not isinstance(case.get("query"), str) or not case["query"].strip():
            raise ValueError("each case needs a non-empty query")
        labels = case.get("relevant_document_ids")
        if not isinstance(labels, list) or not labels or not all(
            isinstance(label, str) and label.strip() for label in labels
        ):
            raise ValueError("each case needs labeled relevant_document_ids")

    results: dict[str, Any] = {}
    for technique in techniques:
        recall, reciprocal_rank, ndcg, latency = [], [], [], []
        for case in cases:
            started = time.perf_counter()
            rows = retrieve(
                tenant_id=tenant_id, query=case["query"], technique=technique,
                vendor_id=case.get("vendor_id"), document_type=case.get("document_type"),
                limit=k, fail_on_missing_collection=True,
            )
            latency.append((time.perf_counter() - started) * 1000)
            relevant = set(case["relevant_document_ids"])
            # Evaluate unique documents; repeated chunks must not inflate scores.
            ranked = list(dict.fromkeys(str(row.get("document_id", "")) for row in rows))
            hits = [int(document_id in relevant) for document_id in ranked]
            recall.append(sum(hits) / len(relevant))
            reciprocal_rank.append(next((1 / i for i, hit in enumerate(hits, 1) if hit), 0.0))
            dcg = sum(hit / math.log2(i + 1) for i, hit in enumerate(hits, 1))
            ideal = sum(1 / math.log2(i + 1) for i in range(1, min(len(relevant), k) + 1))
            ndcg.append(dcg / ideal)
        results[technique] = {
            "recall_at_k": statistics.mean(recall),
            "mrr_at_k": statistics.mean(reciprocal_rank),
            "ndcg_at_k": statistics.mean(ndcg),
            "mean_latency_ms": statistics.mean(latency),
        }
    baseline = results[techniques[0]]
    differences = {
        name: {metric: values[metric] - baseline[metric] for metric in values}
        for name, values in results.items()
    }
    return {"cases": len(cases), "k": k, "baseline": techniques[0],
            "techniques": results, "difference_from_baseline": differences}
