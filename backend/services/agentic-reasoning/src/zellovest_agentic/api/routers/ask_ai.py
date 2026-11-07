"""Ask AI Natural Language Engine router."""

from datetime import UTC, datetime
import asyncio
import json
import time
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from zellovest_agentic.api.deps import get_current_user, get_db_session, normalize_tenant_id
from zellovest_agentic.services.rag_llm import answer_question
from zellovest_agentic.services.tracing import trace_span
from zellovest_agentic.schemas.ask_ai import (
    AskAIRequest,
    AskAIResponse,
    ConversationHistory,
    ConversationListResponse,
)
from zellovest_shared.logging_conf import get_logger
from zellovest_shared.db.models import User
from zellovest_shared.rag import search_documents

logger = get_logger(__name__)
router = APIRouter(prefix="/ask-ai", tags=["ask_ai"])


async def _answer_with_trace(
    question: str,
    tenant_id: str,
    vendor_id: str | None,
    request_id: str,
) -> tuple[list[dict[str, Any]], dict[str, Any], int]:
    """Retrieve evidence and generate a grounded answer under one Langfuse trace."""
    started = time.perf_counter()
    trace_metadata = {
        "request_id": request_id,
        "tenant_id": tenant_id,
        "vendor_filter": bool(vendor_id),
        "question_length": len(question),
    }
    with trace_span("ask_ai.query", trace_metadata) as query_span:
        with trace_span("ask_ai.document_retrieval", {
            "request_id": request_id,
            "tenant_id": tenant_id,
            "vendor_filter": bool(vendor_id),
            "limit": 6,
        }) as retrieval_span:
            retrieval_started = time.perf_counter()
            passages = await asyncio.to_thread(
                search_documents,
                tenant_id=tenant_id,
                query=question,
                vendor_id=vendor_id,
                limit=6,
            )

            if not passages:
                logger.warning(
                    "ask_ai_no_passages_found", tenant_id=tenant_id,
                    hint="Check if documents are indexed in Qdrant for this tenant_id",)

            if retrieval_span:
                retrieval_span.update(metadata={
                    "result_count": len(passages),
                    "latency_ms": int((time.perf_counter() - retrieval_started) * 1000),
                })
        with trace_span("ask_ai.grounded_generation", {
            "request_id": request_id,
            "retrieved_count": len(passages),
        }) as generation_span:
            result = await asyncio.to_thread(answer_question, question, passages)
            if generation_span:
                generation_span.update(metadata={
                    "citation_count": len(result["citations"]),
                    "input_tokens": result["usage"]["input_tokens"],
                    "output_tokens": result["usage"]["output_tokens"],
                })
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        if query_span:
            query_span.update(metadata={
                **trace_metadata,
                "status": "success",
                "retrieved_count": len(passages),
                "citation_count": len(result["citations"]),
                "input_tokens": result["usage"]["input_tokens"],
                "output_tokens": result["usage"]["output_tokens"],
                "processing_time_ms": elapsed_ms,
            })
    return passages, result, elapsed_ms


@router.post("", response_model=AskAIResponse)
async def ask_ai(
    body: AskAIRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> AskAIResponse:
    """Answer a procurement question using tenant-scoped document evidence."""
    del session
    tenant_id = normalize_tenant_id(current_user.tenant_id)
    if body.tenant_id and normalize_tenant_id(body.tenant_id) != tenant_id:
        raise HTTPException(status_code=403, detail="tenant context mismatch")
    request_id = request.state.request_id
    vendor_id = (body.context or {}).get("vendor_id")
    logger.info("ask_ai_requested", request_id=request_id, tenant_id=tenant_id,
                question_length=len(body.question))
    try:
        passages, result, processing_time_ms = await _answer_with_trace(
            body.question, tenant_id, vendor_id, request_id
        )
    except Exception as exc:
        logger.exception("ask_ai_failed", request_id=request_id, tenant_id=tenant_id,
                         error_class=type(exc).__name__)
        raise HTTPException(status_code=503,
                            detail="evidence-based answering is temporarily unavailable") from exc
    logger.info("ask_ai_completed", request_id=request_id, tenant_id=tenant_id,
                citation_count=len(result["citations"]),
                input_tokens=result["usage"]["input_tokens"],
                output_tokens=result["usage"]["output_tokens"])
    return AskAIResponse(
        answer=result["answer"],
        conversation_id=body.conversation_id or uuid4(),
        citations=result["citations"],
        tool_calls=[],
        confidence=(sum(float(item.get("score", 0)) for item in passages[:3]) / min(3, len(passages))) if passages else 0.0,
        generated_at=datetime.now(UTC),
        processing_time_ms=processing_time_ms,
    )


@router.post("/stream")
async def ask_ai_stream(
    body: AskAIRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> StreamingResponse:
    """Ask AI with an SSE response containing grounded answer and citations."""
    del session
    tenant_id = normalize_tenant_id(current_user.tenant_id)
    if body.tenant_id and normalize_tenant_id(body.tenant_id) != tenant_id:
        raise HTTPException(status_code=403, detail="tenant context mismatch")
    conversation_id = body.conversation_id or uuid4()
    request_id = request.state.request_id
    try:
        _, result, _ = await _answer_with_trace(
            body.question,
            tenant_id,
            (body.context or {}).get("vendor_id"),
            request_id,
        )
    except Exception as exc:
        logger.exception("ask_ai_stream_failed", request_id=request_id,
                         tenant_id=tenant_id, error_class=type(exc).__name__)
        raise HTTPException(status_code=503, detail="Ask AI is temporarily unavailable") from exc

    async def generate():
        yield f"data: {json.dumps({'type': 'start', 'conversation_id': str(conversation_id)})}\n\n"
        yield f"data: {json.dumps({'type': 'token', 'content': result['answer']})}\n\n"
        yield f"data: {json.dumps({'type': 'complete', 'citations': result['citations'], 'tool_calls': []})}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


@router.get("/conversations", response_model=ConversationListResponse)
async def list_conversations(
    tenant_id: str = Query(..., min_length=1),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    session: AsyncSession = Depends(get_db_session),
) -> ConversationListResponse:
    """List conversation history for a tenant."""
    logger.info("conversations_listed", tenant_id=tenant_id)
    return ConversationListResponse(
        conversations=[],
        total=0,
        page=page,
        page_size=page_size,
    )


@router.get("/conversations/{conversation_id}", response_model=ConversationHistory)
async def get_conversation(
    conversation_id: str,
    tenant_id: str = Query(..., min_length=1),
    session: AsyncSession = Depends(get_db_session),
) -> ConversationHistory:
    """Get a specific conversation."""
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"Conversation {conversation_id} not found",
    )
