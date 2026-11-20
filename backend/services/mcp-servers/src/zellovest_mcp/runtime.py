"""Shared FastMCP-over-Streamable-HTTP runtime for the three MCP servers.

The runtime centralizes the cross-cutting concerns required by PRD section 25:

* authenticated tenant/actor context from transport headers,
* per-tool request/response schema validation,
* role/scope authorization,
* per-tool timeouts,
* bounded result sizes,
* structured, audited tool results,
* capability discovery derived from the shared contract catalog.

It deliberately avoids reflecting Python function signatures into JSON Schema:
the contract in :mod:`zellovest_shared.mcp_contracts` is the single source of
truth, so the host and every server advertise the same schema.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any

import jsonschema
import mcp.types as types
from jsonschema import FormatChecker
from mcp.server.lowlevel import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from sqlalchemy import text
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route
from zellovest_shared.db.session import get_async_engine
from zellovest_shared.logging_conf import configure_logging, get_logger
from zellovest_shared.mcp_contracts import (
    ToolContract,
    contracts_for_server,
)

from zellovest_mcp.audit import record_invocation
from zellovest_mcp.context import RequestContext, resolve_request_context
from zellovest_mcp.errors import ErrorCode, ToolError
from zellovest_mcp.settings import McpServerSettings, get_mcp_settings

logger = get_logger(__name__)

ToolHandler = Callable[[RequestContext, dict[str, Any]], Awaitable[dict[str, Any]]]

_PUBLIC_PATHS = frozenset({"/healthz", "/readyz"})


class _ServiceAuthMiddleware:
    """Validate the shared service token and inject the request context."""

    def __init__(self, app, settings: McpServerSettings) -> None:  # type: ignore[no-untyped-def]
        self.app = app
        self.settings = settings

    async def __call__(self, scope, receive, send):  # type: ignore[no-untyped-def]
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        if scope.get("path") in _PUBLIC_PATHS:
            await self.app(scope, receive, send)
            return
        headers = {
            key.decode("latin-1").lower(): value.decode("latin-1")
            for key, value in scope.get("headers", [])
        }
        try:
            context = resolve_request_context(headers, self.settings)
        except ToolError as exc:
            body = json.dumps(
                {
                    "error": exc.code.value,
                    "message": exc.message,
                    "correlation_id": headers.get("x-correlation-id"),
                }
            ).encode("utf-8")
            await send(
                {
                    "type": "http.response.start",
                    "status": 401 if exc.code == ErrorCode.UNAUTHENTICATED else 400,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"content-length", str(len(body)).encode("ascii")),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": body})
            return
        scope.setdefault("state", {})["mcp_context"] = context
        await self.app(scope, receive, send)


class _McpAsgi:
    """Adapt the session manager to a plain ASGI application."""

    def __init__(self, manager: StreamableHTTPSessionManager) -> None:
        self.manager = manager

    async def __call__(self, scope, receive, send):  # type: ignore[no-untyped-def]
        await self.manager.handle_request(scope, receive, send)


class McpServerRuntime:
    """A logical MCP server: declared contracts plus concrete handlers."""

    def __init__(
        self,
        *,
        server_name: str,
        display_name: str,
        version: str,
        settings: McpServerSettings | None = None,
    ) -> None:
        """Create the runtime for one logical server.

        Args:
            server_name: Logical server id from the shared contract catalog.
            display_name: Human-readable server title.
            version: Server implementation version.
            settings: Optional settings override (tests).
        """
        self.server_name = server_name
        self.display_name = display_name
        self.version = version
        self.settings = settings or get_mcp_settings()
        self.contracts: dict[str, ToolContract] = {
            contract.name: contract for contract in contracts_for_server(server_name)
        }
        self._handlers: dict[str, ToolHandler] = {}

    def tool(self, name: str) -> Callable[[ToolHandler], ToolHandler]:
        """Register the handler for one declared tool.

        Args:
            name: Tool name declared in the shared catalog.

        Returns:
            Decorator that stores the handler.

        Raises:
            KeyError: When the tool is not declared for this server.
        """
        if name not in self.contracts:
            raise KeyError(f"tool {name!r} is not declared for {self.server_name}")

        def decorator(handler: ToolHandler) -> ToolHandler:
            self._handlers[name] = handler
            return handler

        return decorator

    def _declared_tools(self) -> list[types.Tool]:
        """Return MCP tool descriptors for every declared contract."""
        return [
            types.Tool(
                name=contract.name,
                description=contract.description,
                inputSchema=contract.strict_input_schema(),
                outputSchema=dict(contract.output_schema),
            )
            for contract in self.contracts.values()
        ]

    def _context_from_request(self) -> RequestContext:
        """Resolve the context injected by the HTTP middleware."""
        request = None
        try:
            from mcp.server.lowlevel.server import request_ctx

            request = request_ctx.get().request
        except Exception:
            request = None
        if request is not None:
            context = getattr(request.state, "mcp_context", None)
            if isinstance(context, RequestContext):
                return context
        return resolve_request_context({}, self.settings)

    def _validate(self, contract: ToolContract, arguments: dict[str, Any]) -> None:
        """Validate arguments against the declared input schema.

        Args:
            contract: Tool contract to enforce.
            arguments: Raw tool arguments.

        Raises:
            ToolError: With ``invalid_arguments`` when validation fails.
        """
        try:
            jsonschema.validate(
                instance=arguments,
                schema=contract.strict_input_schema(),
                format_checker=FormatChecker(),
            )
        except jsonschema.ValidationError as exc:
            path = ".".join(str(part) for part in exc.absolute_path) or "arguments"
            raise ToolError(
                ErrorCode.INVALID_ARGUMENTS,
                f"{path}: {exc.message}",
            ) from exc

    async def _dispatch(
        self, name: str, arguments: dict[str, Any]
    ) -> types.CallToolResult:
        """Authorize, execute, audit, and envelope one tool call."""
        started = time.perf_counter()
        contract = self.contracts.get(name)
        if contract is None:
            return _error_result(
                ToolError(ErrorCode.NOT_FOUND, f"tool {name!r} is not served here")
            )
        try:
            context = self._context_from_request()
        except ToolError as exc:
            return _error_result(exc)

        try:
            context.require_scope(contract.auth_scope)
        except ToolError as exc:
            await record_invocation(
                settings=self.settings,
                context=context,
                contract=contract,
                arguments=arguments,
                success=False,
                latency_ms=int((time.perf_counter() - started) * 1000),
                result_size=None,
                error_code=exc.code.value,
                auth_result="denied",
            )
            return _error_result(exc)

        try:
            self._validate(contract, arguments)
        except ToolError as exc:
            await record_invocation(
                settings=self.settings,
                context=context,
                contract=contract,
                arguments=arguments,
                success=False,
                latency_ms=int((time.perf_counter() - started) * 1000),
                result_size=None,
                error_code=exc.code.value,
            )
            return _error_result(exc)

        handler = self._handlers.get(name)
        if handler is None:
            return _error_result(
                ToolError(ErrorCode.INTERNAL, f"tool {name!r} is not implemented")
            )

        try:
            async with asyncio.timeout(contract.timeout_seconds):
                payload = await handler(context, arguments)
        except ToolError as exc:
            await record_invocation(
                settings=self.settings,
                context=context,
                contract=contract,
                arguments=arguments,
                success=False,
                latency_ms=int((time.perf_counter() - started) * 1000),
                result_size=None,
                error_code=exc.code.value,
            )
            return _error_result(exc)
        except TimeoutError:
            error = ToolError(
                ErrorCode.TIMEOUT,
                f"{name} exceeded its {contract.timeout_seconds:g}s timeout",
                retryable=True,
            )
            await record_invocation(
                settings=self.settings,
                context=context,
                contract=contract,
                arguments=arguments,
                success=False,
                latency_ms=int((time.perf_counter() - started) * 1000),
                result_size=None,
                error_code=error.code.value,
            )
            return _error_result(error)
        except Exception as exc:
            logger.exception(
                "mcp_tool_failed",
                tool=name,
                correlation_id=context.correlation_id,
                error_class=type(exc).__name__,
            )
            error = ToolError(
                ErrorCode.INTERNAL,
                f"{name} is temporarily unavailable",
                retryable=True,
            )
            await record_invocation(
                settings=self.settings,
                context=context,
                contract=contract,
                arguments=arguments,
                success=False,
                latency_ms=int((time.perf_counter() - started) * 1000),
                result_size=None,
                error_code=error.code.value,
            )
            return _error_result(error)

        encoded = json.dumps(payload, default=str)
        size = len(encoded.encode("utf-8"))
        latency_ms = int((time.perf_counter() - started) * 1000)
        if size > self.settings.max_result_bytes:
            error = ToolError(
                ErrorCode.INVALID_ARGUMENTS,
                "result exceeds the configured size limit; narrow the request",
                details={"result_bytes": size, "limit": self.settings.max_result_bytes},
            )
            await record_invocation(
                settings=self.settings,
                context=context,
                contract=contract,
                arguments=arguments,
                success=False,
                latency_ms=latency_ms,
                result_size=size,
                error_code=error.code.value,
            )
            return _error_result(error)

        await record_invocation(
            settings=self.settings,
            context=context,
            contract=contract,
            arguments=arguments,
            success=True,
            latency_ms=latency_ms,
            result_size=size,
        )
        summary = payload.get("summary") if isinstance(payload, dict) else None
        return types.CallToolResult(
            content=[
                types.TextContent(
                    type="text",
                    text=summary or f"{name} completed in {latency_ms} ms",
                )
            ],
            structuredContent=payload,
            isError=False,
        )

    def build_app(self) -> Starlette:
        """Build the Streamable HTTP ASGI application.

        Returns:
            Starlette app serving ``/mcp`` plus health and contract-discovery
            endpoints.
        """
        lowlevel = Server(self.display_name, version=self.version)

        @lowlevel.list_tools()
        async def _list_tools() -> list[types.Tool]:
            """Advertise the declared contract catalog."""
            return self._declared_tools()

        @lowlevel.call_tool(validate_input=False)
        async def _call_tool(
            name: str, arguments: dict[str, Any] | None
        ) -> types.CallToolResult:
            """Dispatch one MCP tool call."""
            return await self._dispatch(name, arguments or {})

        session_manager = StreamableHTTPSessionManager(
            app=lowlevel,
            json_response=True,
            stateless=True,
            max_request_body_size=1_048_576,
        )

        async def healthz(request: Request) -> JSONResponse:
            """Liveness probe (no authentication)."""
            return JSONResponse(
                {
                    "status": "ok",
                    "server": self.server_name,
                    "version": self.version,
                    "tools": sorted(self.contracts),
                }
            )

        async def readyz(request: Request) -> JSONResponse:
            """Readiness probe checking both handlers and database access."""
            missing = [name for name in self.contracts if name not in self._handlers]
            if missing:
                return JSONResponse(
                    {"ready": False, "missing_handlers": missing}, status_code=503
                )
            try:
                engine = get_async_engine()
                async with engine.connect() as connection:
                    await connection.execute(text("SELECT 1"))
            except Exception as exc:
                return JSONResponse(
                    {"ready": False, "database": type(exc).__name__}, status_code=503
                )
            return JSONResponse({"ready": True, "server": self.server_name})

        async def list_contracts(request: Request) -> JSONResponse:
            """Expose the machine-readable contract catalog for the host."""
            return JSONResponse(
                {
                    "server": self.server_name,
                    "version": self.version,
                    "tools": [
                        {
                            **contract.as_metadata(),
                            "input_schema": contract.strict_input_schema(),
                            "output_schema": dict(contract.output_schema),
                        }
                        for contract in self.contracts.values()
                    ],
                }
            )

        @asynccontextmanager
        async def lifespan(app):  # type: ignore[no-untyped-def]
            async with session_manager.run():
                logger.info(
                    "mcp_server_started",
                    server=self.server_name,
                    version=self.version,
                    tools=len(self.contracts),
                )
                yield

        app = Starlette(
            routes=[
                Route("/healthz", healthz),
                Route("/readyz", readyz),
                Route("/v1/contracts", list_contracts),
                Mount("/mcp", app=_McpAsgi(session_manager)),
            ],
            lifespan=lifespan,
        )
        app.add_middleware(_ServiceAuthMiddleware, settings=self.settings)
        return app


def _error_result(error: ToolError) -> types.CallToolResult:
    """Convert a typed tool error into an MCP error result.

    The model sees an explicit ``isError`` result with a stable code, so a
    failed tool never looks like an empty dataset (PRD 25.8).
    """
    return types.CallToolResult(
        content=[
            types.TextContent(
                type="text",
                text=f"{error.code.value}: {error.message}",
            )
        ],
        structuredContent={
            "error": error.to_payload(),
            "available": False,
        },
        isError=True,
    )


def configure_server_logging(settings: McpServerSettings) -> None:
    """Configure structured logging for a server process."""
    configure_logging()
    logger.info("mcp_settings_loaded", server=settings.service_name)
