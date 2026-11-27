# Document RAG operations

## Index and search behavior

Digital extraction uses PyMuPDF layout blocks and PDFPlumber tables; scanned
input uses Document AI. The chunker keeps page and section boundaries, uses
block and table coordinates when available, removes text blocks mostly covered
by a detected table, and repeats column headers with table rows. If reliable
table coordinates or block coverage are unavailable it retains extracted page
text as well as tables; duplicates are preferable to silently losing source
text. Parents are page-specific and adjacent pages in the same section are
linked. The assistant receives each neighboring page as separate evidence with
its own citation, so a citation cannot attach text to the wrong page. Parents
are stored once as vectorless Qdrant points and loaded for selected children.
Legacy child payloads with embedded parents remain readable.

Indexing publishes only after all parent and child batches have been staged.
Failed staged batches stay invisible; older active points are removed after
publication. A cleanup failure after publication can leave two visible
generations until the worker retries. Per-document indexing holds a database
row lock, and source retrieval checks that the document still exists for the
tenant. Artifact cleanup retries failures. Monitor task failures and retry
exhaustion: the asynchronous deletion fallback is not a durable outbox.

Search uses tenant, vendor, document and type constraints in both dense and
sparse prefetches, Qdrant RRF, parent diversification, and an optional Voyage
reranker. Set `RAG_RERANK_MODEL` only when its extra provider calls and costs
are approved. Search falls back to RRF if that call fails. `date_from` and
`date_to` are inclusive **UTC dates added**, resolved from PostgreSQL within
Document Knowledge MCP; they do not mean effective dates or renewal dates.
Logs include tenant, counts, timing, and error class, not source passages.

## Staged rebuild and rollback

1. Deploy the new readers everywhere before the new index workers, because
   older readers do not understand staged points or separate parent records.
   Confirm that legacy search still works. Back up the current collection and
   database using the deployment's normal backup process.
2. Create a Qdrant alias such as `zellovest_documents_active` pointing to the
   current physical collection. Set `QDRANT_COLLECTION` to that alias for all
   readers and writers and restart them. Set `QDRANT_MIRROR_COLLECTION` to a
   new physical collection on every indexing and cleanup process. The indexer
   creates that collection as needed. Keep the old physical collection intact.
3. From the worker image, run `python /app/rag_reindex.py backfill --tenant
   TENANT --target zellovest_documents_v2`. Run `verify` with the same
   arguments. Backfill is resumable by repeating it; it reprocesses all eligible
   documents and therefore incurs embedding cost. Verify compares source
   fingerprints, generation counts, parent/child counts, references, and
   orphans. Both commands fail if the target resolves to the active collection.
   Repeat for every tenant represented in the collection: an alias switch
   changes the collection for all tenants, not just the one being verified.
4. Evaluate old and new collections with the same reviewed labels as described
   in `rag-benchmark.md`. Investigate retrieval, citation, latency, and cost
   regressions. The code does not claim a quality improvement without a run.
5. Before switching, stop document and vendor mutations, pause new ingestion,
   drain in-flight indexing and cleanup tasks, and wait for workers to finish.
   Re-run backfill and verification for every tenant in the collection. If
   verification reports orphans, run `prune` with the same tenant and target
   arguments plus `--writers-paused`, then verify again. Do not switch if any
   expected document is missing, stale, duplicated, or orphaned. An empty
   eligible set is not accepted as a successful verification.
6. Switch the alias in one Qdrant `POST /collections/aliases` request using
   `delete_alias` followed by `create_alias` pointing at the new physical
   collection. While writers remain paused, set `QDRANT_MIRROR_COLLECTION`
   to the old physical collection on all indexing and cleanup processes and
   restart them. This keeps the old collection current during the rollback
   window. Resume writes and monitor both sides.
7. To roll back, pause and drain writes again, atomically point the alias back
   to the old collection, configure the new collection as mirror, restart the
   processes, and resume. Do not assume a collection is rollback-ready if
   mirroring was disabled or any mirrored write or cleanup failed. Keep backups
   until reconciliation, evaluation, and the rollback window are complete.

The CLI does not switch aliases or delete active collections. It does not
prove that traffic was paused; the operator must enforce that prerequisite.
The benchmark and CLI are copied into the worker image. For local use, set
`PYTHONPATH` to `shared/src` and `services/workers/src` and run them from
`backend`. These operations are not an online transactional migration: the
final write pause prevents a verification/cutover race.
