# zellovest-ingestion-api

Service 3 — Ingestion & Document Ingress API (FastAPI, :8003): Ramp/Drive OAuth, webhooks (Ramp/Okta/Drive push), pull sync (Ramp/Drive), manual upload fallback, sync dispatch (metadata-only Celery tickets).

## Endpoint groups (Ramp and Drive share the same shape)

| Purpose | Ramp | Google Drive |
|---|---|---|
| OAuth connect | `POST /api/v1/integrations/ramp/connect` | `POST /api/v1/integrations/google-drive/connect` |
| OAuth callback | `GET /api/v1/integrations/ramp/callback` | `GET /api/v1/integrations/google-drive/callback` |
| Connection status | `GET /api/v1/integrations/ramp/status` | `GET /api/v1/integrations/google-drive/status` (includes watch health) |
| Push webhook | `POST /api/v1/webhooks/ramp` | `POST /api/v1/webhooks/google-drive` (`X-Goog-*` headers; `sync` acked, changes enqueue a background pull) |
| Pull sync (polling) | `POST /api/v1/sync/ramp` (`card_transactions`, `bills`) | `POST /api/v1/sync/google-drive` (`changes.list` from checkpoint cursor) |

Notes:

- The generic multi-platform `/api/v1/connectors` CRUD (`POST/GET/DELETE /connectors`, `/connectors/{id}/sync`, `/connectors/{id}/files`) has been removed. Single-tenant Drive state lives in `tenant_integrations` (`provider='google_drive'`, one row per provider per tenant — see migration `0002_drive_provider`) plus Redis watch mappings (`drive:watch:{channel}` → tenant, `drive:channel:{tenant}` → watch health).
- OAuth states are provider-bound: a Ramp-issued `state` is rejected by the Drive callback and vice versa.
- Drive callback creates the `changes.watch` push channel best-effort (failures only warn; pull sync keeps working). Watch entries expire — re-running OAuth (or a renewal job) re-establishes the channel.
- `POST /sync/google-drive` writes a PENDING checkpoint (`entity='documents'`, cursor = explicit `cursor` or latest SUCCESS cursor; `full_sync` re-seeds `startPageToken`) and enqueues Celery task `zellovest.workers.tasks.ingestion.sync_drive_changes` (queue `ingestion_tasks`; worker pages Drive and fans files out to `document_tasks` for OCR & extraction).
- Okta is webhook-only (`POST /api/v1/webhooks/okta`); no pull-sync endpoint.
- Manual fallback upload (staging to S3/MinIO): `POST /api/v1/uploads`, `GET /uploads`, `GET /uploads/{id}`, `POST /uploads/{id}/process`.

## Env

- `GOOGLE_DRIVE_CLIENT_ID` / `GOOGLE_DRIVE_CLIENT_SECRET` — Drive OAuth app.
- `GOOGLE_DRIVE_AUTH_URL` (default `https://accounts.google.com/o/oauth2/v2/auth`) / `GOOGLE_DRIVE_TOKEN_URL` (default `https://oauth2.googleapis.com/token`) / `GOOGLE_DRIVE_REDIRECT_URI` — must end in `/api/v1/integrations/google-drive/callback`.
- `GOOGLE_DRIVE_WEBHOOK_TOKEN` — shared secret echoed as the watch `token`, verified on `X-Goog-Channel-Token`.
- `GOOGLE_DRIVE_WEBHOOK_CALLBACK_URL` — public `https://…/api/v1/webhooks/google-drive` callback for `changes.watch`.
- `S3_RAW_BUCKET` / `S3_ENDPOINT_URL` — staging bucket for manual uploads (MinIO in dev).
