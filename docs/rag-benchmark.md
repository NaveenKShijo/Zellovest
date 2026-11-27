# Retrieval benchmark

Use a fixed, human-reviewed set of questions and relevant source document IDs
from the same tenant. This benchmark compares dense, sparse, and hybrid search
on the configured Qdrant collection. Keep the labels and query set unchanged
when comparing index versions; do not treat model-generated labels as ground
truth. Never commit customer questions or document identifiers to the repo.

Create a local JSON file in this format:

```json
[
  {
    "query": "What is the renewal notice period?",
    "relevant_document_ids": ["document-uuid"],
    "vendor_id": "optional-vendor-uuid",
    "document_type": "contract"
  }
]
```

From `backend`, with the project environment and services configured, run:

```powershell
$env:PYTHONPATH = "shared/src"
python benchmark_rag.py path/to/labels.json --tenant tenant-id --k 10
```

The report contains document-level Recall@k, MRR@k, nDCG@k, mean wall-clock
latency, and differences relative to dense search. Rankings are deduplicated by
document after retrieving at most k child chunks; repeated chunks therefore
consume retrieval slots but do not inflate document scores. A missing index or
retrieval error fails the run. Scores for short benchmark sets are unstable;
include different document types, tables, exact identifiers, semantic queries,
and difficult negatives. Label all relevant documents for each query.

To compare chunking or enrichment versions, run the same labels and settings
against each separately built collection, recording collection and model
versions alongside results. This tool does not reindex, judge answer quality,
or establish passage-level relevance. The existing `/rag/evaluate` endpoint is
an LLM-judge workflow and its scores are not a substitute for labeled recall.
