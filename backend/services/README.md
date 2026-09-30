# Zellovest Backend — Microservices (per PRD 27.5)

Single-tenant, service-oriented layout. Each customer deployment runs all
services isolated (own Postgres, Redis, S3 bucket, vector namespace).

## Services

| Service | Package | Port | Responsibility |
|---|---|---:|---|
| procurement-core | `zellovest_procurement` | 8001 | Tenants, vendors, invoices/POs CRUD, spend analytics, approval workflows |
| agentic-reasoning | `zellovest_agentic` | 8002 | Ask AI (SSE), negotiation copilot, RAG orchestration, tool sandbox = MCP host/client |
| ingestion-api | `zellovest_ingestion` | 8003 | Ramp/Okta webhooks, cloud-drive connectors, upload staging, sync dispatch |
| workers | `zellovest_workers` | — | Celery: ingestion + document OCR + AP audit + maverick ML + zombie licenses |
| shared | `zellovest_shared` | — | Config, DB models/session/repo, schemas, security, Ramp/S3/rate-limit clients |

## Queues

- `ingestion_tasks` — Ramp polling, webhook handlers, Okta sync
- `document_tasks` — document OCR & extraction (Worker 4)
- `analytics_tasks` — AP audit (Worker 5), maverick spend (Worker 6), zombie licenses (Worker 7)

## Run locally

Docker (full single-tenant stack):

```bash
cd backend
docker compose -f docker-compose.microservices.yml --env-file .env up --build
# procurement-core :8001/docs, agentic-reasoning :8002/docs, ingestion-api :8003/docs
```

Directly in `.venv` (no Docker). The service packages resolve via
`.venv/Lib/site-packages/zellovest_microservices.pth` (recreate it if the
venv is ever rebuilt — it just lists `shared/src` + each `services/*/src`):

```bash
cd backend
uv run uvicorn zellovest_ingestion.main:app --port 8003 --reload
uv run uvicorn zellovest_procurement.main:app --port 8001 --reload
uv run uvicorn zellovest_agentic.main:app --port 8002 --reload
uv run celery -A zellovest_workers.celery_app.celery_app worker -Q ingestion_tasks,document_tasks,analytics_tasks --loglevel=info
```

Prerequisites: copy `.env.example` to `.env` and fill in secrets
(`JWT_SECRET_KEY` and `CREDENTIALS_ENCRYPTION_KEY` are mandatory —
the apps fail fast without them). Offline: prefix uv commands with
`--no-sync` / use `uv sync --offline --extra dev` (see `wheels/README.md`).

## Rules (PRD)

- Deterministic financial logic lives in workers/services, never in the LLM.
- Agent accesses data only via MCP tools (MCP-1 structured, MCP-2 documents,
  MCP-3 external actions); no raw SQL / bucket browsing.
- High-risk writes require human confirmation; every tool call is auditable
  with tenant, actor, latency, and correlation ID.
- All backend code lives in `services/*` + `shared/` (the old `src/zellovest`
  monolith was removed after the migration; nothing may import from it).
