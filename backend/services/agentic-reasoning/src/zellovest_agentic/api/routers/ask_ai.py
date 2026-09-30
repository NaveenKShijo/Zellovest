"""Ask AI Natural Language Engine router."""

from datetime import UTC, datetime
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from zellovest_agentic.api.deps import get_db_session
from zellovest_agentic.schemas.ask_ai import (
    AskAIRequest,
    AskAIResponse,
    ConversationHistory,
    ConversationListResponse,
)
from zellovest_shared.logging_conf import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/ask-ai", tags=["ask_ai"])


@router.post("", response_model=AskAIResponse)
async def ask_ai(
    body: AskAIRequest,
    session: AsyncSession = Depends(get_db_session),
) -> AskAIResponse:
    """Ask a natural language question to the procurement AI."""
    logger.info("ask_ai_requested", tenant_id=body.tenant_id, question_length=len(body.question))
    
    # TODO: Implement actual agentic reasoning with MCP tools
    # For now, return a mock response
    return AskAIResponse(
        answer="This is a placeholder response. The Ask AI engine will use MCP servers to query procurement data, documents, and external systems to provide evidence-backed answers.",
        conversation_id=uuid4(),
        citations=[],
        tool_calls=[],
        confidence=0.0,
        generated_at=datetime.now(UTC),
        processing_time_ms=0,
    )


@router.post("/stream")
async def ask_ai_stream(
    body: AskAIRequest,
    session: AsyncSession = Depends(get_db_session),
) -> StreamingResponse:
    """Ask AI with streaming SSE response."""
    logger.info("ask_ai_stream_requested", tenant_id=body.tenant_id)
    
    async def generate():
        yield "data: {\"type\": \"start\", \"conversation_id\": \"" + str(uuid4()) + "\"}\n\n"
        yield "data: {\"type\": \"token\", \"content\": \"This is a streaming placeholder response. \"}\n\n"
        yield "data: {\"type\": \"token\", \"content\": \"The Ask AI engine will use MCP servers to query procurement data. \"}\n\n"
        yield "data: {\"type\": \"token\", \"content\": \"Documents and external systems for evidence-backed answers.\"}\n\n"
        yield "data: {\"type\": \"complete\", \"citations\": [], \"tool_calls\": []}\n\n"
    
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