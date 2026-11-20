"""Ask AI: natural-language procurement analyst (MCP host).

Every request flows through the agent pipeline: conversation state -> plan ->
MCP-1/2/3 tools -> evidence-grounded synthesis -> Answer + Evidence + Proposed
Actions. Streaming uses SSE for the UI only; MCP transport is Streamable HTTP.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from zellovest_agentic.agent import (
    ActionService,
    AgentAnswer,
    AskAIAgent,
    ConversationNotFound,
    ConversationStore,
)
from zellovest_agentic.api.deps import (
    build_mcp_identity,
    get_current_user,
    get_db_session,
    normalize_tenant_id,
)
from zellovest_agentic.mcp import McpHostError
from zellovest_agentic.schemas.ask_ai import (
    ActionConfirmRequest,
    ActionConfirmResponse,
    ActionPreviewRequest,
    ActionPreviewResponse,
    AskAIRequest,
    AskAIResponse,
    ConversationHistory,
    ConversationListResponse,
)
from zellovest_shared.db.models import User
from zellovest_shared.logging_conf import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/ask-ai", tags=["ask_ai"])

_ERROR_STATUS: dict[str, int] = {
    "forbidden": status.HTTP_403_FORBIDDEN,
    "not_found": status.HTTP_404_NOT_FOUND,
    "invalid_arguments": status.HTTP_422_UNPROCESSABLE_CONTENT,
    "confirmation_required": status.HTTP_409_CONFLICT,
    "conflict": status.HTTP_409_CONFLICT,
    "timeout": status.HTTP_504_GATEWAY_TIMEOUT,
    "unavailable": status.HTTP_503_SERVICE_UNAVAILABLE,
    "circuit_open": status.HTTP_503_SERVICE_UNAVAILABLE,
}


def _agent_for(request: Request) -> AskAIAgent:
    """Return the app-scoped agent, creating it lazily for tests."""
    agent = getattr(request.app.state, "ask_ai_agent", None)
    if agent is not None:
        return agent
    from zellovest_agentic.config import get_agentic_reasoning_settings
    from zellovest_agentic.mcp import McpPool

    settings = getattr(request.app.state, "settings", None) or get_agentic_reasoning_settings()
    request.app.state.settings = settings
    pool = McpPool(settings)
    request.app.state.mcp_pool = pool
    agent = AskAIAgent(settings, pool)
    request.app.state.ask_ai_agent = agent
    return agent


def _action_service_for(request: Request) -> ActionService:
    """Return the app-scoped action service, creating it lazily for tests."""
    service = getattr(request.app.state, "action_service", None)
    if service is not None:
        return service
    from zellovest_agentic.config import get_agentic_reasoning_settings
    from zellovest_agentic.mcp import McpPool

    settings = getattr(request.app.state, "settings", None) or get_agentic_reasoning_settings()
    pool = getattr(request.app.state, "mcp_pool", None) or McpPool(settings)
    request.app.state.mcp_pool = pool
    service = ActionService(settings, pool)
    request.app.state.action_service = service
    return service


def _enforce_tenant(current_user: User, requested: str | None) -> str:
    """Return the caller's tenant, rejecting cross-tenant requests."""
    tenant_id = normalize_tenant_id(current_user.tenant_id)
    if requested and normalize_tenant_id(requested) != tenant_id:
        raise HTTPException(status_code=403, detail="tenant context mismatch")
    return tenant_id


def _response(answer: AgentAnswer) -> AskAIResponse:
    """Map the internal agent answer onto the API schema."""
    from datetime import UTC, datetime

    return AskAIResponse(
        answer=answer.answer,
        conversation_id=answer.conversation_id,
        citations=answer.citations,
        tool_calls=answer.tool_calls,
        confidence=answer.confidence,
        generated_at=datetime.now(UTC),
        processing_time_ms=answer.processing_time_ms,
        evidence=answer.evidence,
        proposed_actions=answer.proposed_actions,
        data_gaps=answer.data_gaps,
        sections=answer.sections,
        intent=answer.intent,
        plan_source=answer.plan_source,
        trace_id=answer.trace_id,
    )


def _action_http_error(exc: McpHostError) -> HTTPException:
    """Translate a controlled MCP error into an HTTP response."""
    return HTTPException(
        status_code=_ERROR_STATUS.get(exc.code, status.HTTP_502_BAD_GATEWAY),
        detail={"code": exc.code, "message": exc.message, "tool": exc.tool},
    )


@router.post("", response_model=AskAIResponse)
async def ask_ai(
    body: AskAIRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> AskAIResponse:
    """Answer a procurement question through the MCP tool boundary."""
    del session
    tenant_id = _enforce_tenant(current_user, body.tenant_id)
    identity = build_mcp_identity(current_user, request.state.request_id)
    logger.info(
        "ask_ai_requested",
        request_id=request.state.request_id,
        tenant_id=tenant_id,
        question_length=len(body.question),
        has_context=bool(body.context),
    )
    try:
        answer = await _agent_for(request).answer(
            question=body.question,
            identity=identity,
            context=body.context,
            conversation_id=body.conversation_id,
            user_id=current_user.id,
            auto_execute_actions=body.auto_execute_actions,
        )
    except ConversationNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="conversation not found",
        ) from exc
    except Exception as exc:  # noqa: BLE001 - request boundary
        logger.exception(
            "ask_ai_failed",
            request_id=request.state.request_id,
            tenant_id=tenant_id,
            error_class=type(exc).__name__,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Ask AI is temporarily unavailable",
        ) from exc
    return _response(answer)


@router.post("/stream")
async def ask_ai_stream(
    body: AskAIRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> StreamingResponse:
    """Ask AI with SSE progress events and a final Answer + Evidence payload."""
    del session
    tenant_id = _enforce_tenant(current_user, body.tenant_id)
    identity = build_mcp_identity(current_user, request.state.request_id)
    agent = _agent_for(request)
    queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()

    async def emit(event: dict[str, Any]) -> None:
        """Push one SSE event from the pipeline."""
        await queue.put(event)

    async def run() -> AgentAnswer:
        """Run the pipeline and always terminate the event stream."""
        try:
            return await agent.answer(
                question=body.question,
                identity=identity,
                context=body.context,
                conversation_id=body.conversation_id,
                user_id=current_user.id,
                auto_execute_actions=body.auto_execute_actions,
                emit=emit,
            )
        finally:
            await queue.put(None)

    def sse(payload: dict[str, Any]) -> str:
        """Serialize one SSE frame."""
        return f"data: {json.dumps(payload, default=str)}\n\n"

    async def generate():
        """Forward pipeline events and the final structured payload."""
        task = asyncio.create_task(run())
        try:
            while True:
                event = await queue.get()
                if event is None:
                    break
                yield sse(event)
            exception = task.exception()
            if exception is not None:
                if isinstance(exception, ConversationNotFound):
                    yield sse(
                        {
                            "type": "error",
                            "code": "conversation_not_found",
                            "message": "conversation not found",
                        }
                    )
                else:
                    logger.error(
                        "ask_ai_stream_failed",
                        request_id=request.state.request_id,
                        tenant_id=tenant_id,
                        error_class=type(exception).__name__,
                    )
                    yield sse(
                        {
                            "type": "error",
                            "code": "unavailable",
                            "message": "Ask AI is temporarily unavailable",
                        }
                    )
                return
            answer = task.result()
            yield sse(
                {
                    "type": "complete",
                    "conversation_id": str(answer.conversation_id),
                    **_response(answer).model_dump(mode="json"),
                }
            )
        finally:
            if not task.done():
                task.cancel()

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/conversations", response_model=ConversationListResponse)
async def list_conversations(
    request: Request,
    tenant_id: str | None = Query(default=None, max_length=128),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
) -> ConversationListResponse:
    """List this user's Ask AI conversations."""
    tenant = _enforce_tenant(current_user, tenant_id)
    store = ConversationStore(enabled=request.app.state.settings.agent_conversation_persistence)
    conversations, total = await store.list_conversations(
        tenant_id=tenant,
        user_id=current_user.id,
        page=page,
        page_size=page_size,
    )
    return ConversationListResponse(
        conversations=conversations,
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/conversations/{conversation_id}", response_model=ConversationHistory)
async def get_conversation(
    conversation_id: str,
    request: Request,
    tenant_id: str | None = Query(default=None, max_length=128),
    current_user: User = Depends(get_current_user),
) -> ConversationHistory:
    """Return one conversation with its ordered, structured messages."""
    tenant = _enforce_tenant(current_user, tenant_id)
    store = ConversationStore(enabled=request.app.state.settings.agent_conversation_persistence)
    try:
        return await store.get_conversation(
            tenant_id=tenant,
            user_id=current_user.id,
            conversation_id=conversation_id,
        )
    except ConversationNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="conversation not found",
        ) from exc


@router.post("/actions/preview", response_model=ActionPreviewResponse)
async def preview_action(
    body: ActionPreviewRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
) -> ActionPreviewResponse:
    """Return a side-effect-free dry-run preview of a proposed action."""
    identity = build_mcp_identity(current_user, request.state.request_id)
    try:
        payload = await _action_service_for(request).preview(
            identity=identity,
            tool=body.tool_name,
            arguments=body.arguments,
        )
    except McpHostError as exc:
        raise _action_http_error(exc) from exc
    return ActionPreviewResponse(**payload)


@router.post("/actions/confirm", response_model=ActionConfirmResponse)
async def confirm_action(
    body: ActionConfirmRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
) -> ActionConfirmResponse:
    """Execute a high-risk action after explicit human confirmation."""
    identity = build_mcp_identity(current_user, request.state.request_id)
    try:
        payload = await _action_service_for(request).confirm(
            identity=identity,
            tool=body.tool_name,
            arguments=body.arguments,
            idempotency_key=body.idempotency_key,
            conversation_id=body.conversation_id,
            user_id=current_user.id,
            note=body.confirmation_note,
        )
    except McpHostError as exc:
        raise _action_http_error(exc) from exc
    except ConversationNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="conversation not found",
        ) from exc
    return ActionConfirmResponse(**payload)


__all__ = ["router"]
