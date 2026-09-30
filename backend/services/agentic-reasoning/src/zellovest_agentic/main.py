"""Agentic Reasoning & Ask AI Service - FastAPI Application.

Handles:
- Ask AI Natural Language Engine
- Negotiation Copilot Agent
- RAG Orchestration Layer
- Tool Calling Sandbox Engine
"""

import uuid
from contextlib import asynccontextmanager

import redis
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from zellovest_agentic.api.routers import ask_ai, negotiation, rag, tools
from zellovest_agentic.config import get_agentic_reasoning_settings
from zellovest_shared.logging_conf import configure_logging, get_logger

configure_logging()
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Attach settings + Redis client to app state."""
    settings = getattr(app.state, "settings", None) or get_agentic_reasoning_settings()
    app.state.settings = settings
    try:
        app.state.redis = redis.Redis.from_url(settings.redis_url, decode_responses=False)
    except Exception as exc:
        logger.warning("redis_connect_failed", error_class=type(exc).__name__)
        app.state.redis = None
    yield


def create_app(settings=None) -> FastAPI:
    """Build the FastAPI application for Agentic Reasoning Service."""
    app = FastAPI(
        title="Zellovest Agentic Reasoning & Ask AI Service",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
    )
    app.state.settings = settings or get_agentic_reasoning_settings()

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
    app.include_router(ask_ai.router, prefix=prefix, tags=["ask_ai"])
    app.include_router(negotiation.router, prefix=prefix, tags=["negotiation"])
    app.include_router(rag.router, prefix=prefix, tags=["rag"])
    app.include_router(tools.router, prefix=prefix, tags=["tools"])

    @app.get("/healthz", tags=["ops"])
    def healthz() -> dict:
        return {"status": "ok", "service": "agentic-reasoning"}

    @app.get("/readyz", tags=["ops"])
    def readyz(request: Request) -> JSONResponse:
        client = getattr(request.app.state, "redis", None)
        if client is None:
            return JSONResponse(status_code=503, content={"ready": False, "redis": "unconfigured"})
        try:
            client.ping()
        except Exception:
            return JSONResponse(status_code=503, content={"ready": False, "redis": "unreachable"})
        return JSONResponse(status_code=200, content={"ready": True, "service": "agentic-reasoning"})

    return app


app = None
try:
    app = create_app()
except Exception:
    app = None  # type: ignore[assignment]