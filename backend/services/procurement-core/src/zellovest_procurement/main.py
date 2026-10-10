"""Procurement Core Service - FastAPI Application.

Handles:
- Tenant & Vendor Management
- Manual Invoices / POs CRUD
- Spend Analytics Aggregators
- Action & Approval Workflow
"""

import uuid
from contextlib import asynccontextmanager

import redis
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from zellovest_procurement.api.routers import tenants, vendors, invoices, purchase_orders, analytics, workflows, auth
from zellovest_procurement.config import get_procurement_core_settings
from zellovest_shared.logging_conf import configure_logging, get_logger

configure_logging()
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Attach settings + Redis client to app state for dependency injection."""
    settings = getattr(app.state, "settings", None) or get_procurement_core_settings()
    app.state.settings = settings
    try:
        app.state.redis = redis.Redis.from_url(settings.redis_url, decode_responses=False)
    except Exception as exc:
        logger.warning("redis_connect_failed", error_class=type(exc).__name__)
        app.state.redis = None
    yield


def create_app(settings=None) -> FastAPI:
    """Build the FastAPI application for Procurement Core Service.

    Args:
        settings: Injected settings (tests); defaults to env settings.

    Returns:
        Configured FastAPI app.
    """
    app = FastAPI(
        title="Zellovest Procurement Core Service",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
    )
    app.state.settings = settings or get_procurement_core_settings()

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
    app.include_router(tenants.router, prefix=prefix, tags=["tenants"])
    app.include_router(vendors.router, prefix=prefix, tags=["vendors"])
    app.include_router(invoices.router, prefix=prefix, tags=["invoices"])
    app.include_router(purchase_orders.router, prefix=prefix, tags=["purchase_orders"])
    app.include_router(analytics.router, prefix=prefix, tags=["analytics"])
    app.include_router(workflows.router, prefix=prefix, tags=["workflows"])

    @app.get("/healthz", tags=["ops"])
    def healthz() -> dict:
        """Liveness probe (no dependencies)."""
        return {"status": "ok", "service": "procurement-core"}

    @app.get("/readyz", tags=["ops"])
    def readyz(request: Request) -> JSONResponse:
        """Readiness probe: pings Redis."""
        client = getattr(request.app.state, "redis", None)
        if client is None:
            return JSONResponse(status_code=503, content={"ready": False, "redis": "unconfigured"})
        try:
            client.ping()
        except Exception:
            return JSONResponse(status_code=503, content={"ready": False, "redis": "unreachable"})
        return JSONResponse(status_code=200, content={"ready": True, "service": "procurement-core"})

    return app


app = None
try:
    app = create_app()
except Exception:
    # Import-time env may be absent (docs/tests); create_app() is canonical.
    app = None  # type: ignore[assignment]