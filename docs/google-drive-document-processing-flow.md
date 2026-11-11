# Google Drive Sync and Document Processing Flow

This document describes the execution path in the current Zellovest codebase
when a user starts a Google Drive sync. It covers both kinds of Drive sync and
continues through document extraction, classification, indexing, structured
extraction, verification, and final persistence.

The PRD defines the intended product architecture. The source files linked in
this document are authoritative for the behavior that currently executes.

## 1. The complete flow at a glance

```text
User clicks Sync Now or Full Load
        |
        v
Frontend POST /api/v1/sync/google-drive
        |
        v
Ingestion API
  - resolves/reuses a checkpoint
  - enqueues sync_drive_changes
  - commits the checkpoint
  - returns HTTP 202
        |
        v
Celery ingestion_tasks queue
        |
        v
Google Drive worker
  - loads OAuth credentials
  - refreshes the token when necessary
  - runs files.list for a full import, or changes.list incrementally
  - writes Drive metadata to the bronze lake
  - downloads processable files to GCS
  - creates an Upload lease
  - enqueues process_document
        |
        v
Celery document_tasks queue
        |
        v
Document worker
  - downloads the raw file from GCS
  - identifies content by magic bytes
  - chooses Python extraction or Document AI
  - writes the extraction artifact
  - queues Jev classification
        |
        v
Classification and promotion
  - Jev classification, with keyword fallback
  - creates or reuses a Document row
  - queues RAG indexing
  - queues structured extraction for supported business documents
        |
        +-----------------------> RAG/Qdrant indexing
        |
        v
Structured extraction, when applicable
  - Groq JSON extraction
  - Jev field verification
  - escalation or human review when required
  - vendor resolution
  - invoice/PO/contract/amendment upsert
  - invoice reconciliation fan-out
```

There are two independent asynchronous boundaries:

1. The API acknowledges the sync before Google Drive is contacted.
2. The Drive worker stores each eligible file in GCS before the document worker
   processes it.

The sync worker and document worker therefore do not need to run in the same
process or complete at the same time.

## 2. What the user action does

The Google Drive controls are implemented in
[`frontend/src/app/integrations/page.tsx`](../frontend/src/app/integrations/page.tsx).

### Incremental Sync Now

The `Sync Now` button calls `triggerDriveSync(false)` at
[`page.tsx#L1122`](../frontend/src/app/integrations/page.tsx#L1122). The request
body is:

```ts
{
  tenant_id: tenantId,
  full_sync: false,
}
```

The frontend sends it to `/api/v1/sync/google-drive` using `POST`; see
[`page.tsx#L193-L207`](../frontend/src/app/integrations/page.tsx#L193-L207).

When `full_sync` is false, the backend normally resumes from the latest
successful Drive checkpoint cursor.

### Full Load

The `Full Load` button calls `triggerDriveSync(true)`. This causes
the dispatcher to ignore the stored successful cursor and create a new
backfill checkpoint.

OAuth connection only connects the account and does not start any automatic
data ingestion. The initial full load is triggered only when the user explicitly
clicks the `Full Load` button.

### Important distinction

The frontend calls the same API endpoint for both operations. The difference is
the `full_sync` flag. The worker receives only the resulting cursor value:

- Incremental sync: a cursor is normally supplied.
- Full import: the dispatcher sends `cursor=None`, which tells the worker to
  run the full-import branch.

## 3. API layer: accepting the request

The endpoint is registered in
[`backend/services/ingestion-api/src/zellovest_ingestion/api/routers/sync.py`](../backend/services/ingestion-api/src/zellovest_ingestion/api/routers/sync.py).
The router is mounted under the API's `/api/v1` prefix, so the public path is:

```text
POST /api/v1/sync/google-drive
```

The current endpoint begins at
[`sync.py#L138`](../backend/services/ingestion-api/src/zellovest_ingestion/api/routers/sync.py#L138):

```python
@router.post(
    "/google-drive",
    response_model=SyncResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def trigger_drive_sync(
    body: DriveSyncRequest,
    session: AsyncSession = Depends(get_db_session),
) -> SyncResponse:
    sync_id, task_id, created = await dispatch_drive_sync(
        session,
        tenant_id=body.tenant_id,
        cursor=body.cursor,
        full_sync=body.full_sync,
        page_size=body.page_size,
    )
    await session.commit()
    return SyncResponse(
        sync_id=str(sync_id),
        task_id=task_id,
        status="PENDING",
        deduped=not created,
    )
```

The implementation also emits structured logs before dispatch and before the
response. It does not call Google Drive and does not wait for a worker result.

### Request validation

`DriveSyncRequest` is defined in
[`schemas/sync.py#L24-L40`](../backend/services/ingestion-api/src/zellovest_ingestion/schemas/sync.py#L24-L40):

| Field | Current behavior |
| --- | --- |
| `tenant_id` | Required string, 1–128 characters |
| `cursor` | Optional `changes.list` page-token override |
| `full_sync` | Boolean, default `false` |
| `page_size` | Integer from 1 through 1000, default 100 |

An invalid `page_size`, such as `0`, is rejected by FastAPI/Pydantic with
HTTP 422 before the dispatcher is called.

### Response

The endpoint returns HTTP 202 with a `SyncResponse` containing:

```json
{
  "sync_id": "<checkpoint UUID>",
  "task_id": "<Celery task UUID or existing:<checkpoint UUID>>",
  "status": "PENDING",
  "deduped": false
}
```

`deduped=true` means that an already-open checkpoint was reused and no second
Drive task was queued.

## 4. Dispatcher: checkpoint, deduplication, and enqueue

The dispatcher is in
[`sync_dispatcher.py`](../backend/services/ingestion-api/src/zellovest_ingestion/services/sync_dispatcher.py).
The Drive-specific implementation starts at
[`sync_dispatcher.py#L175`](../backend/services/ingestion-api/src/zellovest_ingestion/services/sync_dispatcher.py#L175).

### Cursor selection

The dispatcher applies this precedence:

1. An explicit request cursor wins.
2. Otherwise, for an incremental request, it reads the latest successful
   `documents` cursor from `ingestion_sync_checkpoints`.
3. A full import deliberately skips the stored cursor.

The lookup is performed by `aget_latest_success_cursor` in
[`repository.py#L364`](../backend/shared/src/zellovest_shared/db/repository.py#L364).

### Sync mode and checkpoint

The dispatcher records:

```python
mode = SyncMode.BACKFILL if (full_sync or cursor) else SyncMode.INCREMENTAL
```

It then calls `acreate_pending_checkpoint` with:

```python
entity=EntityType.DOCUMENTS
cursor_token=effective_cursor
force_new=full_sync
```

The checkpoint starts in `PENDING`. The repository reuses a checkpoint when the
same tenant/entity/mode already has a `PENDING` or `RUNNING` checkpoint. A full
import sets `force_new=True`, so it intentionally creates a fresh checkpoint.
The checkpoint model and state values are in
[`models.py#L107-L141`](../backend/shared/src/zellovest_shared/db/models.py#L107-L141),
and the creation logic is in
[`repository.py#L232-L304`](../backend/shared/src/zellovest_shared/db/repository.py#L232-L304).

### Celery enqueue

The control plane does not import the Drive task directly. `_enqueue_drive` at
[`sync_dispatcher.py#L150`](../backend/services/ingestion-api/src/zellovest_ingestion/services/sync_dispatcher.py#L150)
uses the task name:

```python
async_result = celery_app.send_task(
    "zellovest.workers.tasks.ingestion.sync_drive_changes",
    kwargs=kwargs,
)
```

The payload contains only identifiers and control data:

```json
{
  "tenant_id": "...",
  "cursor": "...",
  "sync_id": "...",
  "page_size": 100
}
```

The dispatcher clamps the page size again to `1..1000` before enqueueing. The
task is routed to `ingestion_tasks` by its task declaration and Celery routing
configuration; see
[`celery_app.py#L12-L51`](../backend/services/workers/src/zellovest_workers/celery_app.py#L12-L51)
and [`ingestion.py#L1728-L1757`](../backend/services/workers/src/zellovest_workers/tasks/ingestion.py#L1728-L1757).

The API commits the newly created checkpoint after dispatch returns. It then
returns immediately to the browser.

## 5. Drive worker: authentication and sync selection

The registered Celery task is
`zellovest.workers.tasks.ingestion.sync_drive_changes`. Its public wrapper is
at [`ingestion.py#L1728`](../backend/services/workers/src/zellovest_workers/tasks/ingestion.py#L1728),
and it delegates to `_sync_drive` at
[`ingestion.py#L1028`](../backend/services/workers/src/zellovest_workers/tasks/ingestion.py#L1028).

The worker performs these steps:

1. Loads worker settings and opens a synchronous database session.
2. Loads the checkpoint by `sync_id`.
3. Changes the checkpoint from `PENDING` to `RUNNING` and commits.
4. Loads the tenant's encrypted `google_drive` integration row.
5. Decrypts the access and refresh tokens.
6. Refreshes the access token when it is expired and a refresh token exists.
7. Creates a `GoogleDriveClient`.
8. Chooses the full or incremental Drive strategy.
9. Always closes the Drive client in a `finally` block.
10. Marks the checkpoint `SUCCESS` with the final cursor.

If a token cannot be refreshed, the provider status is marked expired or
revoked, the checkpoint is marked `FAILED`, and the task raises a permanent
Drive error. Unexpected failures also mark the checkpoint `FAILED` with a
bounded error message.

### Actual branch selection

```python
if cursor:
    result = _sync_drive_changes(..., cursor=cursor)
else:
    result = _sync_drive_full(...)
```

An expired `changes.list` cursor raises `DriveCursorExpiredError`. The worker
then logs the condition and reseeds through the full-import path.

## 6. Full import: `files.list`

The full-import implementation is `_sync_drive_full` at
[`ingestion.py#L786`](../backend/services/workers/src/zellovest_workers/tasks/ingestion.py#L786).

This is one of the important differences from the earlier explanation: a full
import does not page `changes.list`. It calls `get_start_page_token`, then lists
the current files with `files.list`.

The current behavior is:

1. Obtain a new Drive start page token for future incremental work.
2. Read configured folder IDs, if any.
3. Call `client.list_files` for each configured folder, or the whole Drive when
   no folder IDs are configured.
4. Deduplicate files seen across folder queries by Drive file ID.
5. Record every discovered file in the bronze metadata batch.
6. Skip Drive folders.
7. Fan out each other file through `_fan_out_drive_file` with
   `force_reprocess=True`.
8. Write each page's metadata records as gzipped JSONL.
9. Return the original start token as the cursor for the next incremental sync.

Full-import per-file failures are logged and counted as skipped so one bad
download or enqueue does not abort the entire backfill.

## 7. Incremental sync: `changes.list`

The incremental implementation is `_sync_drive_changes` at
[`ingestion.py#L900`](../backend/services/workers/src/zellovest_workers/tasks/ingestion.py#L900).

For each page, it:

1. Calls `client.list_changes_page(token, page_size=page_size)`.
2. Builds a tenant-tagged record for every change.
3. Handles removed files and trashed files as metadata records.
4. Avoids processing the same file ID twice within the task.
5. Skips removed, trashed, and folder entries.
6. Fans out eligible files to the document pipeline.
7. Writes the page records to the bronze lake as gzipped JSONL.
8. Saves `next_page` as the running checkpoint cursor and commits.
9. Continues while another page token exists.
10. Uses the new start token as the final cursor when the page stream ends.

The checkpoint therefore records progress after each page, making a later sync
able to resume from the last committed cursor.

### Bronze metadata record

Each change includes the tenant, provider, sync ID, removal flag, change time,
and the original Drive metadata. The records are written under the documents
bronze entity folder through `_write_drive_records`.

## 8. File fan-out: Drive to GCS to document task

`_fan_out_drive_file` is implemented at
[`ingestion.py#L631`](../backend/services/workers/src/zellovest_workers/tasks/ingestion.py#L631).

### Eligibility

The current processable MIME rules are:

```python
_DRIVE_PROCESSABLE_MIMES = ("application/pdf", "image/")
```

Therefore, PDFs and image files are downloaded for document processing. Google
Drive folders and other non-document MIME types are recorded but not sent to
OCR/extraction.

### Stable object key

The raw file is written to a tenant-scoped key:

```text
drive/{tenant_id}/{file_id}/{safe_filename}
```

The filename is sanitized to remove path traversal, control characters, and
excessive length.

### Upload lease and idempotency

The worker looks up an `Upload` row by `gcs_key`. If the row is already
`PENDING` or `PROCESSING`, the file is skipped during incremental processing.
Full imports pass `force_reprocess=True`, allowing an intentional re-import.

The worker then:

1. Downloads the Drive file, retrying transient Google Drive errors up to three
   times.
2. Skips empty data.
3. Writes the bytes to the raw GCS bucket.
4. Creates or updates the PostgreSQL `Upload` row as `PROCESSING`.
5. Commits the lease before enqueueing document processing.
6. Calls `process_document.delay(...)` with the tenant, GCS key, and upload ID.

If enqueueing the document task fails after the lease is committed, the upload
is marked `FAILED` and the exception is raised. This prevents an apparently
active processing lease from remaining indefinitely after a handoff failure.

The resulting handoff is:

```text
Google Drive bytes
        |
        +--> raw GCS object: drive/{tenant}/{file}/{filename}
        |
        +--> uploads row: status=PROCESSING
        |
        +--> document_tasks: process_document
```

Unlike the manual upload path, Drive fan-out calls `process_document` directly;
it does not use the separate `stage_document` task.

## 9. Document worker entrypoint

The main document task is `process_document` at
[`document_ocr.py#L365-L618`](../backend/services/workers/src/zellovest_workers/tasks/document_ocr.py#L365-L618).
It runs on `document_tasks`.

The important current behavior is:

```python
data = _download_blob(bucket, gcs_key)
triage_result = triage_document_from_bytes(data)
extraction_result = extract_document(
    data=data,
    file_type=triage_result.file_type,
    route=triage_result.route,
)
```

If the GCS object is absent, the task marks the upload `FAILED` and returns a
failure result. If extraction returns an error, it also marks the upload
`FAILED`.

On success, the task:

1. Gets the filename from the GCS key.
2. Runs content-based triage.
3. Runs the selected extraction implementation.
4. Performs a preliminary keyword document classification.
5. Builds document and entity provenance.
6. Persists the full extraction artifact to GCS and its metadata to PostgreSQL.
7. Queues Stage-2 Jev classification.
8. Returns an `indexing` result containing text, pages, entities, tables, and
   artifact information.

The task does not mark the upload `COMPLETED` at this point. Completion occurs
after downstream indexing succeeds.

## 10. Phase 1: content-based triage

The triage code is in
[`document_triage.py`](../backend/services/workers/src/zellovest_workers/tasks/document_triage.py).

### Magic-byte detection

`identify_file_type` at
[`document_triage.py#L82-L108`](../backend/services/workers/src/zellovest_workers/tasks/document_triage.py#L82-L108)
examines the first 16 bytes. It recognizes:

| Content signature | Detected type | Next route |
| --- | --- | --- |
| `%PDF-` | PDF, then analyzed further | Python or Document AI |
| `II*` or `MM*` | TIFF | Document AI |
| PNG signature | PNG | Document AI |
| Anything else | Unknown | Document AI |

The stored MIME hint and filename extension are deliberately ignored for route
selection.

### Digital versus scanned PDF

`analyze_pdf` at
[`document_triage.py#L111-L171`](../backend/services/workers/src/zellovest_workers/tasks/document_triage.py#L111-L171)
uses PyMuPDF to inspect every page. A page counts as text-bearing when it has at
least 40 non-whitespace characters. A PDF is considered digital only when:

- At least 100 qualifying text characters exist in total.
- At least 70% of pages contain at least 40 qualifying characters.

Otherwise, the PDF is classified as `scanned_pdf` and routed to Document AI.

The triage entrypoint is
[`document_triage.py#L174-L274`](../backend/services/workers/src/zellovest_workers/tasks/document_triage.py#L174-L274).

## 11. Phase 2: extraction dispatch

`extract_document` is at
[`document_extract.py#L631-L660`](../backend/services/workers/src/zellovest_workers/tasks/document_extract.py#L631-L660).

```python
if route == "python" and file_type == "digital_pdf":
    return extract_digital_pdf(data)

if route == "document_ai":
    return extract_ocr(data, file_type, client=document_ai_client)

return extract_ocr(data, file_type, client=document_ai_client)
```

The final fallback is Document AI, so an unknown or mismatched route does not
silently produce an empty Python extraction.

### Digital PDF route

`extract_digital_pdf` at
[`document_extract.py#L331-L500`](../backend/services/workers/src/zellovest_workers/tasks/document_extract.py#L331-L500)
uses:

- PyMuPDF for page text, text blocks, bounding boxes, and image detection.
- PDFPlumber for tables.

It returns a common `ExtractionResult` containing full text, page structures,
tables, and the extraction method `pymupdf_pdfplumber`.

Entity extraction is not performed by this route at this stage; structured
business fields are extracted later by the type-specific structured-extraction
task.

### Document AI route

`extract_ocr` at
[`document_extract.py#L502-L629`](../backend/services/workers/src/zellovest_workers/tasks/document_extract.py#L502-L629)
creates a `RealDocumentAIClient` from the configured project, location, and
processor ID when no test client is injected.

It maps the detected type to a MIME type, sends the raw bytes to Google Cloud
Document AI, and normalizes the response into:

- Full text.
- Page text and blocks.
- Tables.
- Entities with confidence, page, and bounding-box data.

The real client builds a regional Document AI endpoint when the configured
location is not `us`; its request and response parsing are implemented earlier
in the same file.

## 12. Extraction artifact and provenance

After extraction, `process_document` writes a complete JSON artifact to:

```text
artifacts/{tenant_id}/{upload_id}/extraction.json
```

The artifact contains:

- Triage result and detection method.
- Extraction route and method.
- Full text.
- Page structures, blocks, tables, and entities.
- Preliminary classification.
- Document-level and entity-level provenance.

An `ExtractionArtifact` row stores queryable metadata, including the source GCS
key, artifact GCS key, route, file type, text length, extraction confidence,
and the first approximately 4,000 characters of text. That snippet is the
input for Stage-2 classification.

If an upload has an `upload_id` and the artifact cannot be persisted, the
upload is marked `FAILED` and classification is not queued.

## 13. Stage-2 classification with Jev

The classification task is registered at
[`document_classify.py#L431-L538`](../backend/services/workers/src/zellovest_workers/tasks/document_classify.py#L431-L538)
and runs on `document_tasks`.

The task reads the extracted text snippet from PostgreSQL and submits a typed
Choice decision to Jev through OpenRouter. Supported types are:

```text
invoice
purchase_order
contract
amendment
policy
other
```

If Jev is unavailable, returns invalid output, or is not configured, the task
falls back to the keyword classifier. The fallback is recorded as
`classification_method="keyword_fallback"`; classification failure does not
discard successful OCR/extraction.

The task persists the final document type, confidence, and classification
method on the `Upload` row and updates the artifact's classification history.

## 14. Promotion, indexing, and structured extraction

After classification, `classify_upload` queues `promote_document`.

### Document promotion

`promote_document` is in
[`document_promote.py#L55-L210`](../backend/services/workers/src/zellovest_workers/tasks/document_promote.py#L55-L210).
It creates or reuses a canonical `Document` row and then queues:

1. `document_index.index_document` for every supported document type.
2. `document_structured_extract.extract_structured` for:
   - `invoice`
   - `purchase_order`
   - `contract`
   - `amendment`

Policies and other documents are promoted and indexed, but do not currently
enter the structured commercial-ledger extraction path.

### RAG indexing

`index_document_task` is in
[`document_index.py#L81-L180`](../backend/services/workers/src/zellovest_workers/tasks/document_index.py#L81-L180).
It reads the extraction artifact, indexes document passages into the configured
RAG store, and marks the upload `COMPLETED` after successful indexing.

If indexing retries are exhausted, its failure hook marks the upload `FAILED`.

### Structured extraction

`extract_structured` is in
[`document_structured_extract.py#L303-L425`](../backend/services/workers/src/zellovest_workers/tasks/document_structured_extract.py#L303-L425).
It calls Groq with a type-specific JSON prompt and returns raw extracted fields
without writing the final business records directly.

Examples of extracted fields include:

- Invoice number, dates, totals, vendor, and line items.
- PO number, dates, totals, vendor, and line items.
- Contract number, dates, renewal terms, vendor, and versioned commercial terms.

When raw extraction succeeds, the task queues `verify_and_upsert`.

## 15. Verification, review, and final persistence

`verify_and_upsert` is in
[`document_verify.py#L1153-L1450`](../backend/services/workers/src/zellovest_workers/tasks/document_verify.py#L1153-L1450).

It performs the final business-data stages:

### Stage 4: Jev field verification

Jev evaluates a field-level verification battery and produces a probability
that each extracted field is wrong.

### Stage 5: escalation gate

The deterministic threshold is `P(wrong) > 0.7`. When exceeded and fewer than
two re-extraction attempts have occurred, the task queues structured extraction
again with the current pipeline.

Contract and amendment documents also require human review when field or
overall extraction confidence is below `0.80`.

### Stage 6: vendor resolution

The extracted vendor name is matched against tenant-scoped vendor records. A
new vendor can be created when no existing match is found.

### Stage 7: idempotent upsert

The task writes the appropriate canonical record:

| Document type | Final database record |
| --- | --- |
| Invoice | Invoice and invoice line items |
| Purchase order | Purchase order and PO line items |
| Contract | Contract, version, lines, terms, and provenance |
| Amendment | Versioned contract changes and amendment provenance |

Successful persistence changes the document status to `extracted`. The task
also queues a refreshed RAG indexing task after vendor resolution. Invoice
upserts enqueue AP reconciliation on the analytics queue.

If verification, vendor resolution, contract lineage, or upsert cannot safely
complete, the document is left in a review-needed path rather than silently
committing uncertain commercial data.

## 16. Queue and storage boundaries

| Responsibility | Celery queue | Main task(s) |
| --- | --- | --- |
| Drive ingestion and sync | `ingestion_tasks` | `sync_drive_changes` |
| Document triage/extraction | `document_tasks` | `process_document` |
| Jev classification | `document_tasks` | `classify_upload` |
| Promotion and indexing | `document_tasks` | `promote_document`, `index_document` |
| Structured extraction | `document_tasks` | `extract_structured` |
| Verification and upsert | `document_tasks` | `verify_and_upsert` |
| Invoice reconciliation | `analytics_tasks` | `reconcile_invoice` |

| Boundary | Current data |
| --- | --- |
| API → Celery | Tenant ID, cursor, sync ID, page size |
| Drive → bronze lake | Tenant-tagged Drive metadata as gzipped JSONL |
| Drive → raw GCS | Original PDF/image bytes under the tenant-scoped Drive key |
| Drive → PostgreSQL | `Upload` processing lease |
| Raw GCS → document worker | File bytes keyed by `gcs_key` |
| Document worker → artifact storage | Full extraction JSON plus `ExtractionArtifact` metadata |
| Classification → canonical model | Document type, confidence, `Document` row |
| Structured extraction → ledger | Verified invoice, PO, contract, or amendment records |

## 17. Differences from the previous walkthrough

The earlier explanation was directionally correct but is not an exact snapshot
of the current repository. The main corrections are:

1. **Full import uses `files.list`.** It obtains a start page token and lists
   existing files. `changes.list` is used for incremental sync.
2. **Cursor recovery exists.** An expired incremental cursor falls back to a
   full import.
3. **Drive token recovery exists.** The worker decrypts credentials and can
   refresh an expired access token before requiring reconnection.
4. **Per-file failures are isolated.** Full-import file failures are logged and
   skipped so the rest of the backfill can continue.
5. **The raw upload lease is not completed by `process_document`.** The upload
   becomes `COMPLETED` after successful document indexing.
6. **Classification is two-stage.** Keyword classification is preliminary;
   Jev classification runs as a separate task and falls back to keywords.
7. **Promotion and RAG indexing are explicit downstream tasks.** They are not
   represented by the return value of the OCR task alone.
8. **Structured extraction is selective.** Only invoice, purchase order,
   contract, and amendment documents enter the commercial-field pipeline.
9. **Verification and human review are implemented.** Jev field verification,
   confidence gates, contract review states, vendor resolution, and final
   upserts occur after raw structured extraction.
10. **Drive API preflight differs from Ramp/Okta.** The current Google Drive
    sync endpoint does not call `_require_usable_integration`; Drive auth and
    failure handling occur in the worker.

## 18. Source map

- Product intent: [`PRD.md`](../PRD.md), especially the document intelligence,
  provenance, asynchronous ingestion, and tenant-isolation sections.
- UI trigger: [`frontend/src/app/integrations/page.tsx`](../frontend/src/app/integrations/page.tsx).
- API and request schema: [`sync.py`](../backend/services/ingestion-api/src/zellovest_ingestion/api/routers/sync.py),
  [`schemas/sync.py`](../backend/services/ingestion-api/src/zellovest_ingestion/schemas/sync.py).
- Checkpoint and enqueue: [`sync_dispatcher.py`](../backend/services/ingestion-api/src/zellovest_ingestion/services/sync_dispatcher.py),
  [`repository.py`](../backend/shared/src/zellovest_shared/db/repository.py).
- Drive worker: [`tasks/ingestion.py`](../backend/services/workers/src/zellovest_workers/tasks/ingestion.py).
- Triage and extraction: [`document_triage.py`](../backend/services/workers/src/zellovest_workers/tasks/document_triage.py),
  [`document_extract.py`](../backend/services/workers/src/zellovest_workers/tasks/document_extract.py).
- Document orchestration: [`document_ocr.py`](../backend/services/workers/src/zellovest_workers/tasks/document_ocr.py),
  [`document_classify.py`](../backend/services/workers/src/zellovest_workers/tasks/document_classify.py),
  [`document_promote.py`](../backend/services/workers/src/zellovest_workers/tasks/document_promote.py).
- Final downstream processing: [`document_index.py`](../backend/services/workers/src/zellovest_workers/tasks/document_index.py),
  [`document_structured_extract.py`](../backend/services/workers/src/zellovest_workers/tasks/document_structured_extract.py),
  [`document_verify.py`](../backend/services/workers/src/zellovest_workers/tasks/document_verify.py).
