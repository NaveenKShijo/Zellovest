# Zellovest MCP Servers

Three independently deployed logical MCP servers (PRD section 25). Each server
runs as its own process and exposes **MCP Streamable HTTP** at `/mcp`; the
Agentic Reasoning Service is the only expected client.

| Server | Id | Port | Entry point |
| --- | --- | --- | --- |
| Procurement Intelligence | `mcp-1-procurement` | 8101 | `zellovest_mcp.main_procurement:app` |
| Document Knowledge | `mcp-2-documents` | 8102 | `zellovest_mcp.main_documents:app` |
| External Systems & Actions | `mcp-3-external` | 8103 | `zellovest_mcp.main_external:app` |

## Design guarantees

* **No generic query tool.** MCP-1 exposes business-level tools only; there is
  no `execute_sql`, and every list is paginated or capped.
* **Tenant boundary from transport, not the prompt.** Tenant/deployment, actor,
  role, and correlation id arrive as headers and are validated before any tool
  runs. Tool arguments never carry a tenant id.
* **Deterministic math.** Money and variance calculations use
  `decimal.Decimal` (`zellovest_shared.pricing`). The LLM never computes
  totals.
* **Risk classes.** `read_only` tools never mutate; `low_risk` writes are
  idempotent and support `dry_run`; `high_risk` writes require an HMAC
  confirmation token bound to the tenant, tool, idempotency key, and exact
  parameters.
* **Honest failures.** Tool failures return `isError=True` with a stable code
  (`integration_unavailable`, `timeout`, ...) so the host distinguishes
  "unavailable" from "zero results".
* **Auditability.** Every invocation writes an `audit_events` row (tenant,
  actor, server/tool/version, risk, auth result, latency, success, result size)
  and a structured log line. Arguments are stored as a SHA-256 digest only.

## Running locally

```powershell
# from backend/
uv run --project services/mcp-servers uvicorn zellovest_mcp.main_procurement:app --port 8101
uv run --project services/mcp-servers uvicorn zellovest_mcp.main_documents:app --port 8102
uv run --project services/mcp-servers uvicorn zellovest_mcp.main_external:app --port 8103
```

All three read `backend/.env`. Relevant settings:

```text
MCP_SERVICE_TOKEN=dev-internal-token
MCP_ALLOW_ANONYMOUS=false
MCP_CONFIRMATION_SECRET=<same value on the host and MCP-3>
MCP_AUDIT_DB_ENABLED=true
ERP_BASE_URL=
ERP_API_TOKEN=
SLACK_BOT_TOKEN=
SLACK_SEARCH_TOKEN=
SMTP_HOST=
SMTP_FROM_ADDRESS=
```

`GET /healthz`, `GET /readyz`, and `GET /v1/contracts` (machine-readable tool
catalog) are available on every server. The MCP endpoint itself requires
`Authorization: Bearer $MCP_SERVICE_TOKEN`.

## Tool catalog

The canonical contract for all 33 tools lives in
`backend/shared/src/zellovest_shared/mcp_contracts.py` and is imported by both
the servers and the host, so provider and consumer cannot drift.
