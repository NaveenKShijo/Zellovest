"""Run a fixed labeled retrieval benchmark against the configured Qdrant index.

Run from backend: python benchmark_rag.py labels.json --tenant TENANT.
The input is a JSON array of objects with query and relevant_document_ids;
optional vendor_id and document_type constrain each query.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from zellovest_shared.rag import search_documents
from zellovest_shared.rag_benchmark import benchmark_retrieval


def main() -> None:
    """Load labels, execute each technique, and print aggregate metrics as JSON."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("labels", type=Path)
    parser.add_argument("--tenant", required=True)
    parser.add_argument("--k", type=int, default=10)
    args = parser.parse_args()
    cases = json.loads(args.labels.read_text(encoding="utf-8"))
    print(json.dumps(benchmark_retrieval(cases, search_documents, tenant_id=args.tenant,
                                         k=args.k), indent=2))


if __name__ == "__main__":
    main()
