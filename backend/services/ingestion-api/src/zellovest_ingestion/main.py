"""Ingestion & Document Ingress API - FastAPI Application.

Endpoint groups (Ramp, Drive and Okta share the same shape):
- OAuth: Ramp (``/integrations/ramp``) + Google Drive
  (``/integrations/google-drive``) + Okta (``/integrations/okta``)
  connect / callback / status.
- Webhooks: Ramp + Okta (hook-secret) + Google Drive push (``changes.watch``).
- Pull sync: Ramp (``POST /sync/ramp``) + Google Drive
  (``POST /sync/google-drive`` via ``changes.list`` cursor) + Okta batch
  (``POST /sync/okta`` for ``users``/``apps``/``logs``; backfill path
  alongside the ``/webhooks/okta`` real-time path).
- File Upload Staging (manual fallback to S3/MinIO)
- Document Triage
"""

import uuid
from contextlib import asynccontextmanager

import redis
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from zellovest_ingestion.api.routers import integrations, integrations_drive, integrations_okta, sync, uploads, webhooks, auth
from zellovest_ingestion.api.routers.integrations_okta import alias_router as integrations_okta_alias_router
from zellovest_ingestion.config import get_ingestion_api_settings
from zellovest_shared.logging_conf import configure_logging, get_logger

configure_logging()
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Attach settings + Redis client to app state."""
    settings = getattr(app.state, "settings", None) or get_ingestion_api_settings()
    app.state.settings = settings
    try:
        app.state.redis = redis.Redis.from_url(settings.redis_url, decode_responses=False)
    except Exception as exc:
        logger.warning("redis_connect_failed", error_class=type(exc).__name__)
        app.state.redis = None
    yield


def create_app(settings=None) -> FastAPI:
    """Build the FastAPI application for Ingestion API."""
    app = FastAPI(
        title="Zellovest Ingestion & Document Ingress API",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
    )
    app.state.settings = settings or get_ingestion_api_settings()

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def correlation_id_middleware(request: Request, call_next):
        request_id = request.headers.get("X-Request-Id", uuid.uuid4().hex)
        response = await call_next(request)
        response.headers["X-Request-Id"] = request_id
        return response

    @app.exception_handler(Exception)
    async def unhandled_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.error("unhandled_error", path=request.url.path, error_class=type(exc).__name__)
        return JSONResponse(status_code=500, content={"detail": "internal server error"})

    prefix = app.state.settings.api_v1_prefix
    app.include_router(auth.router, prefix=prefix, tags=["auth"])
    app.include_router(integrations.router, prefix=prefix, tags=["integrations"])
    app.include_router(integrations_drive.router, prefix=prefix, tags=["integrations"])
    app.include_router(integrations_okta.router, prefix=prefix, tags=["integrations"])
    # Unprefixed legacy alias: GET /okta/callback (already whitelisted on
    # tenants whose Okta app registered the short URL).
    app.include_router(integrations_okta_alias_router, tags=["integrations"])
    app.include_router(webhooks.router, prefix=prefix, tags=["webhooks"])
    app.include_router(uploads.router, prefix=prefix, tags=["uploads"])
    app.include_router(sync.router, prefix=prefix, tags=["sync"])

    @app.get("/healthz", tags=["ops"])
    def healthz() -> dict:
        return {"status": "ok", "service": "ingestion-api"}

    @app.get("/readyz", tags=["ops"])
    def readyz(request: Request) -> JSONResponse:
        client = getattr(request.app.state, "redis", None)
        if client is None:
            return JSONResponse(status_code=503, content={"ready": False, "redis": "unconfigured"})
        try:
            client.ping()
        except Exception:
            return JSONResponse(status_code=503, content={"ready": False, "redis": "unreachable"})
        return JSONResponse(status_code=200, content={"ready": True, "service": "ingestion-api"})

    return app


app = None
try:
    app = create_app()
except Exception:
    app = None  # type: ignore[assignment]
