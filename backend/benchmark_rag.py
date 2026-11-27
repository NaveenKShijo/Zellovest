"""Run a fixed labeled retrieval benchmark against the configured Qdrant index.

Run from backend: python benchmark_rag.py labels.json --tenant TENANT.
The input is a JSON array of objects with query and relevant_document_ids;
optional vendor_id and document_type constrain each query.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from functools import partial
from pathlib import Path

from zellovest_shared.config import get_settings
from zellovest_shared.rag import search_documents
from zellovest_shared.rag_benchmark import benchmark_retrieval


def main() -> None:
    """Load labels, execute each technique, and print aggregate metrics as JSON."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("labels", type=Path)
    parser.add_argument("--tenant", required=True)
    parser.add_argument("--k", type=int, default=10)
    parser.add_argument("--collection", action="append", default=[],
                        help="Collection to test; repeat to compare index versions")
    parser.add_argument("--rerank", action="store_true", help="Also test configured reranker")
    args = parser.parse_args()
    data = args.labels.read_bytes()
    cases = json.loads(data.decode("utf-8"))
    if not isinstance(cases, list):
        raise TypeError("benchmark labels must be a JSON array")
    settings = get_settings()
    collections = args.collection or [settings.qdrant_collection]
    if len(collections) != len(set(collections)):
        raise ValueError("collection names must be unique")
    techniques = ["dense", "sparse", "hybrid"]
    if args.rerank:
        if not settings.rag_rerank_model:
            raise ValueError("set RAG_RERANK_MODEL to benchmark reranking")
        techniques.append("hybrid_rerank")
    reports = {
        collection: benchmark_retrieval(
            cases, partial(search_documents, collection=collection),
            tenant_id=args.tenant, k=args.k, techniques=techniques,
        ) for collection in collections
    }
    baseline = reports[collections[0]]["techniques"]
    differences = {
        collection: {
            technique: {key: value - baseline[technique][key] for key, value in metrics.items()}
            for technique, metrics in report["techniques"].items()
        } for collection, report in reports.items()
    }
    print(json.dumps({"dataset_sha256": hashlib.sha256(data).hexdigest(),
                      "embedding_model": settings.voyage_model,
                      "rerank_model": settings.rag_rerank_model if args.rerank else None,
                      "baseline_collection": collections[0], "collections": reports,
                      "difference_from_baseline_collection": differences}, indent=2))


if __name__ == "__main__":
    main()
