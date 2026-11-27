# Retrieval benchmark

Use a fixed, human-reviewed set of questions and relevant source documents
from the same tenant. Keep the labels and query set unchanged across index
versions. Never commit customer questions or document identifiers to the repo.

Create a local JSON file in this format:

```json
[
  {
    "query": "What is the renewal notice period?",
    "relevant_document_ids": ["document-uuid"],
    "relevant_pages": [{"document_id": "document-uuid", "page": 3}],
    "vendor_id": "optional-vendor-uuid",
    "document_type": "contract"
  }
]
```

`relevant_pages`, `vendor_id`, and `document_type` are optional. From
`backend`, with the project environment and services configured, run:

```powershell
$env:PYTHONPATH = "shared/src"
python benchmark_rag.py path/to/labels.json --tenant tenant-id --k 10 `
  --collection zellovest_documents --collection zellovest_documents_v2
```

The first collection is the index baseline; dense is the technique baseline.
Collections in a single run must use the configured embedding and sparse
models. If an index uses a different embedding model, run it separately with
its matching query model; comparing mismatched vectors is invalid.
The report includes document Recall@k, MRR@k, nDCG@k, hit rate, mean and p95
wall-clock latency, plus differences against both baselines. Optional page
labels produce page Recall@k and MRR@k over the labeled subset. The output
records the label-file hash and model names without printing question text.
Search diversifies by parent before returning up to k children; the benchmark
deduplicates by document or document/page for the respective score. Label every
relevant document and page, and ensure labels are visible under case filters.
A missing index, malformed labels, reranker error, or retrieval error fails
the run rather than contributing an artificial zero.

Add `--rerank` after configuring `RAG_RERANK_MODEL` to compare the paid
reranker; a reranker failure aborts benchmarking even though normal search
falls back to RRF. Run multiple times under comparable load, and interpret
latency alongside provider billing and cold-cache effects. For release review,
use a representative human-reviewed set, require no tenant or citation
isolation failures, inspect page-level changes, and investigate recall, ranking,
or latency regressions before switching. The benchmark does not measure
answer faithfulness, unsupported claims, or answerability. The existing
`/rag/evaluate` endpoint uses generated questions and an LLM judge; its scores
are diagnostic and are not a substitute for independently labeled evaluation.
