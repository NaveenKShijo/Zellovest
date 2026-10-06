# Zellovest — Module Documentation

Module reference for the **AI-Native Procurement Intelligence Platform** (see `PRD.md` for product vision, `TIME.txt` for the week-by-week plan, `AGENTS.md` for coding standards).

Each module below is documented with:

1. **Module Name & Objective** — the problem the block solves.
2. **Components** — frontend screens, backend endpoints, ML models / AI workflows.
3. **Inputs & Outputs** — what data enters and what result is produced.
4. **Timeline Mapping** — which week it is built, tested, and integrated.

---

## Module Index

| ID | Module | Built | Tested | Integrated |
|----|--------------------------------------|-------|--------|------------|
| M1 | Core Data Foundation & Platform Shell | Week 1 | Week 1 | Week 1 (base for all) |
| M2 | Ingestion & External Integrations | Week 1 | Week 1–2 | Week 2 (feeds M3) |
| M3 | Document Intelligence & Contract Ledger | Week 2 | Week 2 | Week 3 → Week 4 (MCP-2) |
| M4 | AP Audit & Reconciliation Engine | Week 3 | Week 3 | Week 4 (Investigation Agent) |
| M5 | Maverick Spend Detection (Jev AI) | Week 3 | Week 3 | Week 4 (MCP-1/MCP-3) |
| M6 | License Utilization & Seat Forecasting | Week 3 | Week 3 | Week 4 (Ask AI) |
| M7 | Renewal Intelligence | Week 3 (data) | Week 3–4 | Week 4 (Renewal Agent) |
| M8 | Agentic Reasoning, Ask AI & MCP Layer | Week 4 | Week 4 | Week 4 (E2E) |
| M9 | Action Workflows & Savings Ledger | Week 4 | Week 4 | Week 4 (E2E) |
| M10 | Deployment, Security & Observability | Week 1 (scaffold) | Week 4 | Week 4 (production) |

---

## M1 — Core Data Foundation & Platform Shell

### Module Name & Objective
Solves **data and UI fragmentation**: establishes the canonical single-tenant data model (vendors, contracts, invoices, POs, transactions, licenses, audit) and the application shell every other module plugs into. Provides unified vendor identity so transactions, contracts, invoices, POs, licenses, and documents resolve to one vendor entity (PRD #2, #29.5).

### Components
**Frontend screens**
- `LayoutShell`, `Sidebar`, `Header`, `Breadcrumbs`, `ToastContainer`, `AlertBanner` — admin layout, responsive viewport, notifications.
- `AuthContext` — basic auth + session handling (single role: procurement team member; no tenant switching in V1).
- Vendor Directory/List (`/vendors`) — active vendors, category tags, annual spend, contract badges, `VendorFilters`, `VendorTable`.
- Vendor 360 Workspace (`/vendors/[id]`) with tabs (`TabNavigation`) for Contracts, Invoices, Transactions, Documents; Add/Edit (`/vendors/new`, `/vendors/[id]/edit`) via `VendorForm`, `VendorHeader`.

**Backend endpoints** (procurement-core, FastAPI :8001)
- `POST/GET/PATCH/DELETE /api/v1/vendors`, `/vendors/{id}` — vendor CRUD.
- `POST/GET/PATCH/DELETE /api/v1/tenants` — deployment/instance record (V1 `tenant_id` = instance ID).
- `shared`: DB models/session/repository (`zellovest_shared.db`), JWT/crypto (`zellovest_shared.security`), Alembic migrations (`0001_initial`).

**ML/AI workflows** — none (deterministic foundation only).

### Inputs & Outputs
- **Inputs:** user/vendor form data (name, domain, contact, payment terms), session credentials; future-ready nullable `org_id` reservation only.
- **Outputs:** canonical vendor records and relational schema (FK-linked contracts, invoices, POs, transactions, licenses, documents) in single-tenant PostgreSQL 16; authenticated app shell serving all later screens.

### Timeline Mapping
- **Built:** Week 1 (frozen) — Postgres schemas, layout shell, vendor CRUD.
- **Tested:** Week 1 — acceptance: login + vendor CRUD pass.
- **Integrated:** Week 1 — foundation consumed by M2 ingestion, M3 documents, M4–M7 analytics, M8 agent tools.

---

## M2 — Ingestion & External Integrations

### Module Name & Objective
Solves **scattered source systems**: pulls corporate card activity, SaaS/identity usage, and procurement documents into the canonical model through asynchronous, incremental, resumable pipelines — with manual upload as fallback (PRD #3, #4, A.1).

### Components
**Frontend screens**
- `/integrations` — Ramp OAuth connect/callback/status, trigger manual sync, connection banners.
- `/upload` — drag-and-drop multi-file upload (`DropZone`), upload queue with progress/status (`UploadQueue`, `UploadProvider`).

**Backend endpoints** (ingestion-api, FastAPI :8003)
- `POST /api/v1/uploads`, `GET /uploads`, `GET /uploads/{id}`, `POST /uploads/{id}/process`, `DELETE /uploads/{id}` — manual fallback: drag-and-drop staging to object storage (S3/MinIO), MIME + size validation.
- `POST /api/v1/webhooks/ramp`, `POST /api/v1/webhooks/okta` — signed webhook ingress.
- `POST /api/v1/webhooks/google-drive` — Drive push callback (`changes.watch`): verifies `X-Goog-Channel-ID` / `X-Goog-Channel-Token` / `X-Goog-Resource-State`; `sync` acked immediately, change events resolve the tenant from the watch mapping and enqueue a background pull (200 OK < 500ms).
- `POST /api/v1/sync/ramp` — Ramp pull sync (`card_transactions`, `bills` only). `POST /api/v1/sync/google-drive` — Drive pull sync (`changes.list` from checkpoint cursor; worker fans files out to `document_tasks`). Okta has no pull-sync endpoint (webhook-only).
- `POST /api/v1/integrations/google-drive/connect`, `GET /integrations/google-drive/callback`, `GET /integrations/google-drive/status` — Drive OAuth (mirrors Ramp): connect, token persistence (`provider='google_drive'`), best-effort `changes.watch` setup, connection + watch health. The generic `/connectors` CRUD has been removed.
- `POST /api/v1/integrations/ramp/connect`, `GET /integrations/ramp/callback`, `GET /integrations/ramp/status` — Ramp OAuth.
- Celery tasks: `ingest_card_transaction_task`, `ingest_okta_directory_task`, `stage_document_task` (queue `ingestion_tasks`); Drive files fan out to `process_document` (queue `document_tasks`).

**ML/AI workflows** — none (normalization only; intelligence happens downstream).

### Inputs & Outputs
- **Inputs:** Ramp card transactions (amount, merchant, MCC, date, cadence), Okta app assignments/user activity/last login, PDF/TIFF document uploads, cloud-drive files; webhook payloads.
- **Outputs:** normalized canonical rows in PostgreSQL; raw files staged in the isolated instance object-storage bucket; queued Celery jobs; sync status for the UI.

### Timeline Mapping
- **Built:** Week 1 — Ramp/Okta connectors, upload staging, Redis + Celery async architecture.
- **Tested:** Week 1 — acceptance: file staged to object storage, Ramp/Okta sync jobs queued, worker health OK.
- **Integrated:** Week 2 — Google Drive connector (Push + Pull) extended; staged documents handed to M3's router; transactions feed M5, usage feeds M6.

---

## M3 — Document Intelligence & Contract Ledger

### Module Name & Objective
Solves **document chaos and lost contractual truth**: routes every document through the cheapest reliable extraction path, classifies it, extracts schema-mapped fields with per-field provenance, preserves contract terms as *versioned* (never overwritten) history, and builds the hybrid RAG index — so a 50-page contract is read once, not per invoice (PRD #5–8, #10–11, #21).

### Components
**Frontend screens**
- Document Explorer — tabbed Contract/MSAs, Amendments, POs, Invoices, Policies views; list tables with search, status pills (Extracted / Review Needed / Failed), vendor tags; Document Detail side-by-side metadata + provenance badge (`/vendors/[id]/documents`, `contracts`, `invoices`).
- Split-pane PDF viewer (react-pdf/PDF.js) with bounding-box highlight overlay, zoom/page nav, citation deep-link Source → Contract → Page.
- HITL review interface — exception drawer for confidence < 0.80, editable commercial terms, "Verify & Commit to Ledger".

**Backend endpoints**
- Document OCR worker (Celery, queue `document_tasks`): `triage_document` → Document Router (pdfplumber deterministic vs Document AI/Textract/Azure DI + LLM) → classifier (invoice / purchase_order / contract / other) → schema mapping → validation branch → provenance tagging.
- RAG endpoints (agentic-reasoning :8002): `POST /api/v1/rag/search`, `POST /rag/upload`, `GET /rag/documents/{id}/chunks`, `GET /rag/documents/{id}/pages/{page}`.
- Versioned contract ledger: `contracts.terms_versioned` (product, price, effective_from/to, currency, UoM, qty limits, discounts, taxes, payment/freight terms) + amendment lineage.

**ML/AI / AI workflows**
- Document classifier + LLM/schema extraction for variable layouts.
- Legal-aware chunker (section-preserving) → embeddings (e.g., text-embedding-3-small) → pgvector/Qdrant `doc_chunks` collection.
- Hybrid search: dense vector similarity + Postgres full-text, vendor/doc/date filters, tenant-scoped (prepares MCP-2).

### Inputs & Outputs
- **Inputs:** raw PDFs/TIFFs (contracts, amendments, invoices, POs, policies) from M2; low-confidence human corrections.
- **Outputs:** classified documents with structured extracted terms; per-field provenance `{field, value, confidence, source_document, page, bounding_box, extraction_method, extracted_at}`; versioned contract-term rows preserving historical states; vector chunks with metadata `{vendor_id, document_id, document_type, page, section}` for RAG.

### Timeline Mapping
- **Built:** Week 2 — router, classifier, schema parsers, HITL, versioning, vector store.
- **Tested:** Week 2 — acceptance: upload → routed → classified → extracted with provenance; low-confidence → HITL; versioned terms queryable; hybrid search returns passage + page/section.
- **Integrated:** Week 3 — versioned terms feed M4 reconciliation; **Week 4** — chunks/provenance served through MCP-2 Document Knowledge to Ask AI.

---

## M4 — AP Audit & Reconciliation Engine

### Module Name & Objective
Solves **contractual/commercial leakage**: deterministically compares every invoice line against the applicable contract *version* at invoice date and flags variances before payment — no LLM does financial math (PRD #9, #12, #26).

### Components
**Frontend screens**
- `/compliance` — AP Audit & Contract Compliance dashboard: KPIs (Total Invoiced, Flagged Discrepancy $, Clean vs Exception counts), reconciliation table (Invoice ID, Vendor, Discrepancy $, Flag Reason: Price Creep, Quantity Tier Mismatch, Missing PO, Discount/Tax/Freight/Date), line-item comparison modal (billed vs contracted price, variance $/%), "Why flagged?" link to Investigation explanation (M8).

**Backend endpoints / workers**
- Celery worker 5 `ap_audit.py` (queue `analytics_tasks`): flow New Invoice → extraction → vendor/product → applicable contract + version @ invoice_date → structured terms → rules → result.
- Rules: unit price ceiling, annual escalation cap, quantity bracket, discount, tax, payment-term, freight, date rules, contract-specific conditions.
- Immutable `reconciliation.exceptions` rows with variance math; `POST/GET /api/v1/workflows` + `/workflows/{id}/action` for exception review/approval routing; `/analytics/spend*` endpoints for dashboard aggregates.

**ML/AI workflows** — deterministic rule engine only (AI explanation added later by M8 Investigation Agent).

### Inputs & Outputs
- **Inputs:** extracted invoices (M3), versioned contract terms (M3), purchase orders, card transactions (M2).
- **Outputs:** immutable discrepancy records with deterministic variance (e.g., contract $120/user vs invoice $140/user → +16.7% → Exception); exception queue for dashboards and agent investigation.

### Timeline Mapping
- **Built:** Week 3.
- **Tested:** Week 3 — acceptance: invoice produces deterministic exception with variance.
- **Integrated:** Week 4 — exceptions exposed via MCP-1 (`get_reconciliation_exception`, `compare_invoice_contract`) and explained by the Investigation Agent.

---

## M5 — Maverick Spend Detection (Jev AI)

### Module Name & Objective
Solves **unmanaged/rogue SaaS spend**: detects recurring software subscriptions bought on corporate cards outside procurement, resolves what the tool does, and matches its capabilities against approved internal software to recommend migration instead of duplication (PRD #14–17).

### Components
**Frontend screens**
- `/maverick-spend` — alert feed of unmanaged recurring SaaS with Jev p-scores (e.g., $20/mo Cursor, ~30d cadence), semantic overlap card (unmanaged tool vs approved alternative, cosine score e.g., GitHub Copilot 0.91) + "Notify Employee to Migrate" action, filters (department, unmanaged spend, overlap threshold).

**Backend endpoints / workers**
- Celery worker 6 `maverick_spend.py` (queue `analytics_tasks`) — 3-stage pipeline:
  1. **Stage 1 — Jev AI Transaction Decisions (TypeSafe AI):** build transaction state (cadence, recurrence interval, dollar magnitude, MCC, merchant/domain, frequency, historical & employee patterns); submit typed questions (`is_unmanaged_saas_subscription`, `warrants_procurement_review`); calibrated p ∈ [0,1] threshold gate. *Replaces the DBSCAN/IsolationForest placeholder.*
  2. **Stage 2 — Context Resolution:** merchant/domain metadata + vendor records + AI-generated capability description.
  3. **Stage 3 — Vector Embedding Retrieval:** embed capability → cosine search vs `software_catalog` (approved software) → alert with overlap score + recommended action.
- MCP-1 tool `get_maverick_spend()`; MCP-3 `send_slack_message()` for employee notification (Week 4).

**ML/AI workflows:** Jev typed probabilistic decision model (Stage 1); LLM capability description (Stage 2); embedding similarity (Stage 3). Doc RAG and capability indexes stay separate.

### Inputs & Outputs
- **Inputs:** normalized Ramp card transactions (M2); approved/contracted software catalog embeddings.
- **Outputs:** flagged unmanaged recurring SaaS subscriptions with probability scores; semantic overlap recommendations (e.g., "approved GitHub Copilot already exists"); `core.alerts` rows for dashboards and agent tools.

### Timeline Mapping
- **Built:** Week 3 — full 3-stage worker.
- **Tested:** Week 3 — acceptance: Jev flags recurring SaaS with p-score + overlap.
- **Integrated:** Week 4 — results via MCP-1 to Ask AI; migration notification via MCP-3.

---

## M6 — License Utilization & Seat Forecasting

### Module Name & Objective
Solves **shelfware and true-up risk**: measures real license utilization, then ML-forecasts the optimal seat commitment at renewal — heuristics like "active + 10%" fail because churn differs wildly by department (PRD #18).

### Components
**Frontend screens**
- `/licenses` — SaaS utilization (purchased vs active logins; 30/60/90-day inactive lists as ML features), waste calculator (inactive seats × contracted unit cost = recoverable annual spend), forecast widget (recommended seat commitment vs current, e.g., 410 vs 500; per-department retention probability curves; best/worst scenarios with confidence intervals; shelfware vs true-up risk $; savings estimate).

**Backend endpoints / workers**
- Celery worker 7 `zombie_license.py` (deterministic batch; legacy rule counts retained as *inputs only*, not forecast output).
- Seat Forecasting worker (ML batch): feature engineering from Okta + renewal data → model → penalty-aware deterministic optimizer → `usage.license_metrics` for dashboards + agent tools.
- MCP-1 tools `get_license_usage()`, `calculate_savings()`.

**ML/AI workflows:** survival analysis / gradient boosted trees (**LightGBM/XGBoost**) producing seat-retention probability curves per department; deterministic penalty-aware optimization layer on top.

### Inputs & Outputs
- **Inputs:** Okta login cadence per user/department, days-since-login, 30/60/90-day frequency, tenure, growth velocity, abandonment curves, contract renewal terms and true-up penalty rates (M2 + M3).
- **Outputs:** per-department seat-retention probability curves; recommended seat commitment with confidence (e.g., "Commit 410 seats — 95% confidence of no true-up, cut $18,000/yr shelfware"); best/worst risk scenarios; recoverable-spend figures.

### Timeline Mapping
- **Built:** Week 3 (ML replaces rule-only "zombie" output).
- **Tested:** Week 3 — acceptance: forecast returns commitment + confidence + $.
- **Integrated:** Week 4 — "How many seats should we commit to?" answered by Ask AI via MCP-1; feeds M7 renewal prep.

---

## M7 — Renewal Intelligence

### Module Name & Objective
Solves **renewal unpreparedness**: continuously monitors upcoming renewals and notice deadlines, then assembles evidence-based renewal/negotiation preparation — the agent *prepares*, the procurement professional decides (PRD #19, #20).

### Components
**Frontend screens**
- `/renewals` — renewal timeline with 120/90/60/30-day badges, auto-renew flag, termination/notice deadline, utilization %, spend YoY.
- Negotiation Copilot & Renewal Agent UI (Week 4) — vendor overview (annual spend, YoY growth, renewal timeline, utilization, unused seats, discrepancies, escalation caps via RAG), Adobe-style renewal prep with leverage actions (remove seats, longer-term pricing, hold unit price, confirm notice deadline), executive brief generator + "Export Brief to PDF".

**Backend endpoints**
- Renewal Monitoring Service (Week 3 data layer): scheduled job scans `renewal_date − notice_period`, persists upcoming renewals, exposes spend + seat + clause inputs.
- Agentic endpoints (Week 4, :8002): `POST /api/v1/negotiation/brief`, `POST /negotiation/renewal-prep`, `GET /negotiation/upcoming-renewals`.
- MCP-1 `find_renewals()`; MCP-3 `create_renewal_reminder()`, `prepare_renewal_brief()`.

**ML/AI workflows:** **Renewal Agent** (investigates contract + spend + usage + invoices + clauses + vendor history) and **Negotiation Copilot** synthesis (hybrid RAG over spend, seats, clauses into a cited brief) — both generative, both human-decision-bound.

### Inputs & Outputs
- **Inputs:** extracted renewal terms (M3), spend history, license utilization (M6), invoice history, previous negotiations, vendor performance, contract clauses.
- **Outputs:** prioritized renewal calendar with notice deadlines; renewal preparation brief (spend, utilization, unused licenses, YoY change, contractual rights, recommended procurement actions); negotiation brief with citations.

### Timeline Mapping
- **Built:** Week 3 (monitoring data layer) → Week 4 (agent + Copilot UI).
- **Tested:** Week 3 — acceptance: renewal list correct at 120/90/60/30 days; Week 4 — brief generation verified E2E.
- **Integrated:** Week 4 — served through MCP-1/MCP-2/MCP-3 to Ask AI and the negotiation workspace.

---

## M8 — Agentic Reasoning, Ask AI & MCP Layer

### Module Name & Objective
Solves **investigation and natural-language access**: gives procurement a conversational analyst that reasons across structured data, documents, ML outputs, and agents — through exactly **three controlled MCP servers**, never raw SQL, buckets, or external credentials (PRD #13, #21–25).

### Components
**Frontend screens**
- `/assistant` — Ask AI / Procurement Investigation Agent workspace: chat history, streaming markdown via SSE (UI streaming only, not MCP transport), citation cards (click → document at exact page + bbox; distinguishes unavailable data vs confirmed zero; separates confirmed facts / calculations / hypotheses / needs-review), coverage across spend, contracts/renewals, invoices/exceptions, licenses/forecast, maverick/overlap, vendor 360, cross-domain questions; inline low-risk actions, high-risk actions behind explicit confirmation modal + dry-run preview.

**Backend endpoints** (agentic-reasoning :8002 — MCP host/client)
- `POST /api/v1/ask-ai`, `POST /ask-ai/stream`, `GET /ask-ai/conversations`, `GET /ask-ai/conversations/{id}`.
- Tool sandbox: `GET /api/v1/tools`, `GET /tools/{tool_name}`, `POST /tools/call` (schema-validated, risk-classed, tenant-scoped, audited).
- RAG: `POST /rag/search`, `POST /rag/upload`, `GET /rag/documents/{id}/chunks`, `GET /rag/documents/{id}/pages/{page}`.
- **MCP Server 1 — Procurement Intelligence:** `get_vendor/contract/invoice/purchase_order`, `get_vendor_spend`, `get_license_usage`, `find_renewals`, `get_reconciliation_exception`, `compare_invoice_contract`, `get_maverick_spend`, `get_spend_trend`, `calculate_spend`, `calculate_savings` (business-level ops only, no `execute_sql`).
- **MCP Server 2 — Document Knowledge:** `search_documents/contracts/invoices/policies/chunks`, `get_document/page/section/provenance`.
- **MCP Server 3 — External Systems:** `lookup_external_vendor`, `search_external_system`, `create_procurement_task/review_task/renewal_reminder`, `prepare_renewal_brief`, `start_human_review_workflow`, `send_slack_message`, `send_email`, `submit_procurement_workflow` (READ / LOW-RISK / HIGH-RISK classes; high-risk needs human confirmation; idempotency keys; dry-run).
- Transport: stdio local dev, **Streamable HTTP** production; per-tool timeouts, correlation IDs, bounded retries, no fabrication on tool failure.

**ML/AI workflows**
- Agentic Reasoning Service: intent classification/planning → tool selection → MCP calls → evidence → LLM synthesis → Answer + Evidence + Proposed Actions.
- **Investigation Agent:** traverses Invoice → Contract → PO → previous invoices → card transactions → amendments/renewals to explain variances (e.g., $140 vs $120 applied to 35 seats when the amendment covered only 20).
- RAG vendor research and cross-domain reasoning.

### Inputs & Outputs
- **Inputs:** user questions (natural language); evidence gathered from M1–M7 via MCP-1/MCP-2; external actions via MCP-3.
- **Outputs:** streamed, cited answers distinguishing facts/calculations/hypotheses/human-review items; proposed low-risk actions executed inline and high-risk actions held for human confirmation; full audit events per tool invocation (correlation/request IDs, actor, server/tool/version, risk, auth result, latency, result size, redacted content).

### Timeline Mapping
- **Built:** Week 4 (foundation: RAG from Week 2, tools/data from Weeks 1–3).
- **Tested:** Week 4 — per PRD #25.12: 3 MCP servers reachable; MCP-1 no raw SQL; MCP-2 returns provenance; MCP-3 risk gating; tenant-scoped + authorized; Streamable HTTP prod; failures don't fabricate.
- **Integrated:** Week 4 — final E2E: Ask AI streaming + citations on public URL, wired to M4 exceptions, M5 alerts, M6 forecasts, M7 briefs.

---

## M9 — Action Workflows & Savings Ledger

### Module Name & Objective
Solves **proving procurement value and closing the loop**: converts detections into tracked workflows and quantifies realized savings — split into hard cash saved vs cost avoidance, with finance sign-off (PRD #24, #30).

### Components
**Frontend screens**
- CFO Realized Savings Ledger — split **Hard Cash Saved** (short-paid/credited overcharges) vs **Cost Avoidance** (maverick canceled, zombie seats de-provisioned); manual "Verified by Finance" confirmation.
- Workflow/task surfaces: procurement tasks, review tasks, renewal reminders, human-review queue (used inline from Ask AI action buttons).

**Backend endpoints**
- `POST/GET /api/v1/workflows`, `GET /workflows/{id}`, `POST /workflows/{id}/action`, `DELETE /workflows/{id}` (procurement-core) — approval/action workflow records.
- `core.savings_ledger` handlers for overbill, seats cut pre-renewal, maverick consolidated.
- MCP-1 `calculate_savings()` (deterministic); MCP-3 low-risk action tools (`create_procurement_task`, `create_review_task`, `create_renewal_reminder`, `start_human_review_workflow`); high-risk tools (`approve_invoice`, `cancel_contract`, `modify_contract_terms`, `change_purchase_order`, `send_external_vendor_communication`, `commit_financial_spend`) gated by explicit human confirmation.

**ML/AI workflows** — none for math: savings calculations are deterministic; the agent only *proposes* ledger entries and actions.

### Inputs & Outputs
- **Inputs:** confirmed reconciliation exceptions (M4), maverick alerts (M5), de-provisioned zombie seats (M6), human finance verification.
- **Outputs:** auditable savings ledger (hard cash vs cost avoidance, verified/potential states); executed or pending workflow tasks; audit trail for every action.

### Timeline Mapping
- **Built:** Week 4.
- **Tested:** Week 4 — savings math verified deterministically; risk gating + human confirmation verified.
- **Integrated:** Week 4 — surfaced in Ask AI responses and dashboards; part of final E2E acceptance.

---

## M10 — Deployment, Security & Observability

### Module Name & Objective
Solves **single-tenant delivery and enterprise trust**: packages every module into an isolated per-customer deployment (dedicated Postgres, Redis, S3 bucket, vector namespace) with TLS, JWT auth, secrets, and auditability for 500–1,000 active users (PRD #27.5, #28, A.6).

### Components
**Frontend screens**
- `/settings` — platform settings: single-tenant deployment configuration and IAM parameters.
- `/integrations` — connection state surfaces (shares with M2).

**Backend / DevOps**
- Docker multi-stage images: Next.js standalone, FastAPI core (3 services), Agentic Reasoning + MCP ×3, Celery workers (Document OCR, AP Audit, Maverick Jev, Forecasting); `docker-compose.microservices.yml` per-customer → K8s/Helm path.
- Traefik/Kong/ALB + Auth0 JWT + tenant injection; NGINX/Caddy reverse proxy (`/api/*` → FastAPI, `/` → Next.js) with SSE timeouts; Streamable HTTP for MCP prod, stdio local.
- Managed PostgreSQL 16 + pgvector, Redis, S3/GCS bucket with IAM; env + LLM/Jev keys via secrets; structured JSON logging (`zellovest_shared.logging_conf`), Prometheus/Grafana, liveness/readiness probes, backups.
- Seeding & E2E: `alembic upgrade head`, seed 10–15 vendors + contracts/amendments + invoices/POs + Ramp + Okta; verify login, upload→OCR, exception→investigation, Ask AI streaming, renewal brief, TLS (Let's Encrypt/Cloudflare).

**ML/AI workflows** — none (platform concern).

### Inputs & Outputs
- **Inputs:** environment configuration, secrets (JWT, credentials encryption, LLM/Jev keys), infrastructure definitions.
- **Outputs:** reproducible single-tenant production deployment with strict isolation, TLS, per-invocation audit logs, and health monitoring.

### Timeline Mapping
- **Built:** Week 1 (compose + worker health scaffold) → Week 4 (production hardening).
- **Tested:** Week 4 — E2E seed + public-URL verification, TLS/SSL check.
- **Integrated:** Week 4 — final acceptance gate for the whole platform.

---

## Cross-Module Rules (from `PRD.md` / `TIME.txt`)

- **Deterministic** for reconciliation, contract rule evaluation, spend/savings math, utilization metrics, authorization. **AI/agents** for investigation, renewal/negotiation preparation, vendor research, natural-language interaction.
- **Evidence-first:** every material claim traces to source document, page, bbox, method, confidence.
- **Single-tenant V1:** no co-mingled data; `tenant_id` in JWT/MCP context = deployment ID; no RLS/org switching.
- **Human-in-the-loop:** low-confidence extraction (<0.80) → review; high-risk actions → explicit confirmation.
- Coding standards per `AGENTS.md`: docstrings, structured logging, robust exception handling, PEP 8.
