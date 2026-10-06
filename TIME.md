# Implementation Timeline — AI-Native Procurement Intelligence Platform

## Global Notes (apply to all weeks)

- Product vision, business logic, and ML/agent boundaries per **PRD.md Sections 1–32 + Appendices A/B**.
- **V1 Scope:** dedicated single-tenant deployment per customer (isolated Postgres DB/schema, object-storage bucket/prefix, vector namespace/collection, Redis). No co-mingled customer data.
- **Future multi-tenant readiness (V1 only):** primary tables include nullable future-ready `org_id UUID` column. No RLS by org_id, no tenant switching, no cross-tenant queries, no tenant-aware routing in V1. `tenant_id` in JWT/MCP context = deployment/instance ID in V1.
- **Single role in V1:** Procurement team member (same capabilities). MCP/tools enforce authorization scopes; granular RBAC hooks reserved.
- **Architecture principle:** deterministic systems for financial/compliance math; AI/agents for investigation/synthesis. Evidence-first (provenance: source doc, page, bbox, method, confidence).
- **Stack:** Next.js 14+ / React, FastAPI (3 core services), Redis + Celery, PostgreSQL 16 + pgvector, S3/GCS/MinIO, Document AI/OCR, LightGBM/XGBoost, Jev AI (TypeSafe), MCP SDK (stdio local / Streamable HTTP prod; SSE only for Ask AI UI streaming).
- **Coding standards per AGENTS.md:** docstrings, structured logging, robust exception handling, PEP 8.

---

## Week 1: Core Data Foundation, Ingestion Pipelines & Base UI Shell

> **Status:** Frozen — no changes; already in progress
> **Modules:** M1 (Core Data Foundation & Platform Shell), M2 (Ingestion & External Integrations), M10 (scaffold)

### Frontend

1. **Application Layout Shell**
   - Admin layout with navigation sidebar, header, global breadcrumbs, responsive viewport.
   - Basic auth + user session handling without tenant switching (single-tenant V1).
   - Core layout state management.
   - Toast and alert notification containers.
2. **Vendor Management**
   - Vendor Directory/List View: active vendors, category tags, annual spend totals, active contract badges.
   - Vendor 360 Workspace shell: contracts, uploaded invoices, card transactions (populated via Week 1 APIs; enriched Weeks 3–4).
   - Vendor Add/Edit: canonical vendor name, domain, primary contact, payment terms; unified vendor identity across transactions/contracts/invoices/POs/licenses/docs.
3. **Document Ingress & Upload UI**
   - Drag-and-drop multi-file upload (PDF, TIFF fallback).
   - Upload queue: progress, file size, staged/queued/processing status.

### Backend & Data

1. **PostgreSQL Setup**
   - Schemas for core data, vendors/users, contracts, billing, invoices, card transactions, audit records.
   - Relational models + FKs; canonical model per deployment.
   - Future-ready `org_id UUID` field on primary tables (reservation only, unused in V1 logic per Global Notes).
2. **Ingress API & File Storage**
   - `POST /api/v1/documents/upload` with MIME-type + file-size validation.
   - Object storage integration (AWS S3 / GCS / MinIO local) with isolated instance bucket.
3. **Data Ingestion Connectors**
   - Ramp connector (REST/scheduled/incremental + webhooks where available): amount, merchant, MCC, date; normalized to canonical model.
   - Okta connector: app assignments, user activity, last login, email, assigned apps.
   - Manual upload as fallback (Drive/S3/Dropbox extended in Week 2).
4. **Async Task Architecture**
   - Redis + Celery (or ARQ), DB connection pooling, health-check endpoints for workers.
   - Baseline tasks: `ingest_card_transaction_task`, `ingest_okta_directory_task`, `stage_document_task`.

### Week 1 Acceptance

- [ ] Login works
- [ ] Vendor CRUD works
- [ ] File staged to object storage
- [ ] Ramp/Okta sync jobs queued
- [ ] Worker health OK

---

## Week 2: Document Intelligence Pipeline, Contract Versioning & Vector Store (RAG Foundation)

> **Per PRD #5–8, #10–11, #21; prepares MCP-2 Document Knowledge**
> **Modules:** M3 (Document Intelligence & Contract Ledger), M2 (connector extension)

### Frontend

1. **Contract & Invoice Repositories (Document Explorer)**
   - Tabbed views: Contracts/MSAs, Amendments, Purchase Orders, Invoices, Vendor Policies/Other.
   - List tables: search, status pills (Extracted, Review Needed, Failed), document dates, vendor tags.
   - Document Detail view: side-by-side extracted structured metadata + document properties + provenance badge.
2. **Split-Pane PDF Viewer & Provenance Highlight**
   - In-browser PDF rendering (react-pdf / PDF.js).
   - Bounding-box overlay: hover/click extracted field highlights exact page coords `[x0,y0,x1,y1]`.
   - Zoom, page navigation, text selection; citation deep-link Source → Contract → Page.
3. **Human-in-the-Loop (HITL) Review Interface**
   - Exception drawer for low-confidence extractions (<0.80).
   - Editable commercial terms: unit price, effective/expiration/renewal dates, renewal notice, auto-renewal flag, escalation caps, payment/freight/tax terms.
   - "Verify & Commit to Ledger" promotes verified terms to operational DB.

### Backend & Data

1. **File Integration Extension**
   - Google Drive / S3 / Dropbox connectors (per PRD A.1) + manual upload; normalize to canonical model; async + incremental sync.
2. **Document Processing & Router Pipeline (per PRD #6–7 diagram)**
   - **Document Router:** digital vector PDFs → pdfplumber deterministic table/text; scanned/raster/variable → cloud OCR (Google Document AI / AWS Textract / Azure AI Document Intelligence) + LLM.
   - **Document Classifier:** Invoice / Purchase Order / Contract / Other.
   - **Schema parsers:** Contracts (vendor, start/end, renewal notice, auto-renew, escalation caps); Invoices (number, issue/due dates, line items, qty, unit price, total).
   - Common Schema → Validation branch: high confidence → DB; low → Human Review → Correction → DB.
   - Provenance per field: `{field, value, confidence, source_document, page, bounding_box, extraction_method, extracted_at}`.
3. **Contract Versioning & Commercial Database**
   - Versioned schema `contracts.terms_versioned`: product, price, effective_from/effective_to, currency, UoM, qty limits, discounts, taxes, payment/freight terms.
   - Amendment lineage: Original → Amendment 1/2 → Renewal → Price Revision; base immutable, child records override only validity windows; preserves history for historical invoice explainability.
4. **Vector Store & Hybrid RAG Indexing**
   - pgvector (or Qdrant) per-tenant namespace. Two collections (distinct purposes per PRD #17): `doc_chunks` (this week) + `software_catalog` (reserved for Week 3 capability matching).
   - Legal chunker: section-aware preserving headers (Termination, Escalation, Governing Law); embeddings (e.g., `text-embedding-3-small`); metadata `{vendor_id, document_id, document_type, page, section/clause_type, raw text}`.
   - Unified hybrid search: dense vector similarity + Postgres full-text (tsvector/BM25); vendor/doc/date filters; no cross-tenant retrieval.

### Week 2 Acceptance

- [ ] Upload → routed → classified → extracted with provenance
- [ ] Low-confidence extractions go to HITL
- [ ] Versioned terms queryable
- [ ] Hybrid search returns passage + page/section

---

## Week 3: Deterministic Engines, Jev Maverick Detection, ML Seat Forecasting & Dashboards

> **Per PRD #9, #12, #14–19; replaces old DBSCAN + rule-only zombie; prepares MCP-1 data**
> **Modules:** M4 (AP Audit), M5 (Maverick Spend), M6 (Seat Forecasting), M7 (Renewal data layer)

### Frontend

1. **AP Audit & Reconciliation Dashboard**
   - Overview KPIs: Total Invoiced, Flagged Discrepancy ($), Clean vs Exception counts.
   - Reconciliation Table: Invoice ID, Vendor, Discrepancy Amount, Flag Reason (Price Creep, Quantity Tier Mismatch, Missing PO, Discount/Tax/Freight/Date rules).
   - Line-Item Comparison Modal: Billed vs Contracted unit price, variance $ and %; "Why flagged?" links to Investigation explanation (Week 4 wiring).
2. **Maverick Spend & Software Overlap Interface (Jev-powered)**
   - Alert feed: unmanaged recurring SaaS with Jev p-scores (e.g., $20/mo Cursor on Ramp, ~30d cadence).
   - Semantic Overlap Card: unmanaged tool vs approved alternative (e.g., GitHub Copilot 0.91 cosine) + "Notify Employee to Migrate" (via MCP-3 in Week 4).
   - Filters: department, unmanaged spend, overlap threshold.
3. **Utilization & Predictive Forecasting Dashboard (ML replaces rule-only zombie)**
   - SaaS Utilization: purchased vs active logins; 30/60/90-day inactive lists (now as ML features, not final output).
   - Waste Calculator: recoverable annual spend (inactive seats × contracted unit cost).
   - **NEW Forecast Widget:** recommended seat commitment vs current (e.g., 410 vs 500), retention probability curve per department, best/worst scenarios with confidence intervals, shelfware vs true-up risk $, savings estimate.
4. **Renewal Timeline (prep for Renewal Agent)**
   - Upcoming renewals with 120/90/60/30-day badges, auto-renew flag, termination/notice deadline, utilization %, spend YoY.

### Backend & Data

1. **Deterministic AP Audit & Compliance Engine (no LLM math)**
   - Flow: New Invoice → Extraction → Identify Vendor/Product → Applicable Contract + Version @ invoice_date → Structured Terms → Rules → Result.
   - Rules: unit price ceiling, annual escalation cap, quantity bracket, discount/tax/payment/freight/date + contract-specific conditions.
   - Immutable discrepancy records in `reconciliation.exceptions` with variance math.
2. **Maverick Spend Detection Worker — 3-stage Jev pipeline (PRD #15–17)**
   - **Stage 1 — Jev AI Transaction Decisions:** build state (cadence, recurrence interval, dollar magnitude/variance, MCC, merchant/domain, frequency, history, employee patterns); submit typed questions (`is_unmanaged_saas_subscription`, `warrants_procurement_review`); calibrated p 0–1 threshold gate. **No DBSCAN/Isolation Forest.**
   - **Stage 2 — Context Resolution:** merchant/domain metadata + external/vendor records + AI capability description (e.g., Cursor → AI code editor, completion/generation).
   - **Stage 3 — Vector Embedding Retrieval:** embed capability, cosine vs `approved_software_catalog`, emit `core.alerts` with overlap score + recommended action. Keep doc RAG vs capability indexes separate.
3. **Seat Forecasting & Churn Worker — ML Batch (PRD #18)**
   - Feature engineering from Okta + renewal data: login cadence per user/dept, days-since-login, 30/60/90 frequency, tenure, growth velocity, abandonment curves, true-up penalty rates.
   - Model: survival analysis / gradient boosted trees (LightGBM/XGBoost) → seat retention probability per department.
   - Penalty-aware deterministic optimizer → recommended commitment + savings + risk scenarios → `usage.license_metrics` for dashboards + agent tools.
   - Old rule-based zombie counts retained only as inputs, not as forecast output.
4. **Renewal Monitoring Service (data layer for Week 4 agent)**
   - Scheduled job scans `renewal_date − notice_period`; persists renewals; exposes spend + seat + clause inputs.

### Week 3 Acceptance

- [ ] Invoice produces deterministic exception with variance
- [ ] Jev flags recurring SaaS with p-score + overlap
- [ ] Forecast returns commitment + confidence + $
- [ ] Renewal list correct at 120/90/60/30

---

## Week 4: Agentic Reasoning, MCP ×3, Copilot, Savings Ledger & Production Deployment

> **Per PRD #13, #19–25, #27–28; Ask AI + Investigation/Renewal/Negotiation agents**
> **Modules:** M8 (Agentic Reasoning & MCP), M9 (Savings Ledger & Workflows), M7 (agent), M10 (Production)

### Frontend

1. **"Ask AI" Conversational Workspace**
   - Chat: history, prompts, streaming markdown via SSE (UI streaming only, not MCP transport).
   - Citation Cards: click opens doc @ exact page + bbox highlight; distinguishes unavailable data vs confirmed zero; shows facts vs calculations vs hypotheses vs needs-review.
   - Coverage per PRD #23: spend, contracts/renewals/escalation/termination, invoices/exceptions, licenses/forecast ("how many seats to commit?"), maverick/overlap, vendor 360, cross-domain ("Why spend up?").
   - Action capabilities: read tools + low-risk (create task/review/renewal reminder/report/brief/human-review) inline; high-risk (approve invoice, cancel contract, modify terms/PO, external vendor comms, commit spend) requires explicit human confirmation modal + dry-run preview.
2. **Negotiation Copilot & Renewal Agent UI**
   - Vendor overview: annual spend, YoY growth, renewal timeline, utilization, unused seats, discrepancies, escalation caps via RAG.
   - Adobe-style Renewal Prep example + leverage actions (remove seats, longer-term pricing, hold unit price, confirm notice deadline).
   - Executive brief generator with citations + "Export Brief to PDF".
3. **CFO Realized Savings Ledger**
   - Split Hard Cash Saved (short-paid/credited overcharges) vs Cost Avoidance (maverick canceled, zombie de-provisioned).
   - Manual "Verified by Finance" confirmation; backed by deterministic `calculate_savings`.

### Backend & Data

1. **Agentic Reasoning Service (MCP Host/Client)**
   - Owns conversation state, intent/planning, tool selection, orchestration, streaming, synthesis (Answer + Evidence + Proposed Actions). No direct Postgres/vector/S3/ERP/Slack access.
   - Flow: User Q → Intent/Planning → MCP-1/MCP-2/MCP-3 → Evidence → LLM Reasoning → Answer + Evidence. Bounded retries (idempotent only), no fabrication on tool failure, per-tool timeouts + correlation IDs.
2. **Three Logical MCP Servers** (separate modules/processes; one deployment initially, independently scalable later)
   - **MCP-1 Procurement Intelligence:** `get_vendor`/`contract`/`invoice`/`purchase_order`, `get_vendor_spend`, `get_license_usage`, `find_renewals`, `get_reconciliation_exception`, `compare_invoice_contract`, `get_maverick_spend`, `get_spend_trend`, `calculate_spend`/`savings`. Business-level ops only (no `execute_sql`); pagination/limits; deterministic math; tenant-scoped + authorized.
   - **MCP-2 Document Knowledge:** `search_documents`/`contracts`/`invoices`/`policies`/`chunks`, `get_document`/`page`/`section`/`provenance`. Filtered retrieval with provenance; no raw bucket/vector browsing; no cross-tenant retrieval; distinguish source vs summary.
   - **MCP-3 External Systems & Actions:** `lookup_external_vendor`, `search_external_system`, `create_procurement_task`/`review_task`/`renewal_reminder`, `prepare_renewal_brief`, `start_human_review_workflow`, `send_slack_message`/`email`, `submit_procurement_workflow`. Risk classes READ / LOW-RISK / HIGH-RISK; high-risk needs human confirm; idempotency keys; dry-run/preview where supported.
   - Tool contract per tool: name, description, input/output schema, auth scope, roles, tenant boundary, read/write + risk, timeout, idempotency, evidence/audit event.
   - Observability/audit per invocation: correlation/request IDs, tenant/deployment, actor, server/tool/version, risk, auth result, latency, success/error, result size (redact sensitive content).
3. **Agent Services (served via MCP + Reasoning Service)**
   - **Procurement Investigation Agent:** traverses Invoice → Contract → PO → Prev Invoices → Card Tx → Amendments/Renewals; explains e.g., $140 vs $120 on 35 vs 20 seats.
   - **Renewal Agent:** investigates contract + spend + usage + invoices + clauses; prepares actions; human retains negotiation authority.
   - **Negotiation Copilot synthesis:** aggregates spend, seats, clauses via hybrid RAG into cited brief.
4. **Savings Ledger:** `core.savings_ledger` for verified/potential; handlers for overbill, seats cut pre-renewal, maverick consolidated.
5. **DevOps & Production Deployment (single-tenant per customer)**
   - Docker multi-stage: Next.js standalone, FastAPI core, Agentic Reasoning + MCP ×3, Celery workers (Document OCR, AP Audit, Maverick Jev, Forecasting); docker-compose per-customer → K8s/Helm path; Traefik/Kong/ALB + Auth0 JWT + tenant injection; NGINX/Caddy reverse proxy (`/api/*` → FastAPI, `/` → Next.js) with SSE timeouts; Streamable HTTP for MCP prod, stdio local; managed PG16+pgvector, Redis, S3/GCS bucket with IAM; env + LLM/Jev keys via secrets.
   - Seeding & E2E: `alembic upgrade head`, seed 10–15 vendors + contracts/amendments, invoices/POs, Ramp, Okta; verify login via public URL, PDF upload→OCR, exception + investigation, Ask AI streaming + citations, renewal brief, TLS/SSL (Let's Encrypt/Cloudflare).

### Week 4 Acceptance (per PRD #25.12)

- [ ] 3 MCP servers reachable
- [ ] MCP-1 no raw SQL
- [ ] MCP-2 returns provenance
- [ ] MCP-3 risk gating works
- [ ] Tenant-scoped + authorized
- [ ] Streamable HTTP prod
- [ ] Failures don't fabricate
- [ ] Ledger + brief + Ask AI E2E pass on public URL

---

## Week → Module Mapping

| Week | Focus | Modules |
|------|-------|---------|
| **Week 1** | Core data foundation, ingestion pipelines, base UI shell | M1, M2, M10 (scaffold) |
| **Week 2** | Document intelligence, contract versioning, vector store (RAG) | M3, M2 (extension) |
| **Week 3** | Deterministic engines, Jev maverick detection, ML forecasting, dashboards | M4, M5, M6, M7 (data) |
| **Week 4** | Agentic reasoning, MCP ×3, copilot, savings ledger, production deployment | M7 (agent), M8, M9, M10 |
