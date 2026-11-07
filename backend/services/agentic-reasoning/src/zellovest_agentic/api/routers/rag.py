"""Document search and LLM-judge evaluation endpoints."""

import asyncio
import hashlib
import os
import time
from uuid import UUID, uuid4

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from zellovest_agentic.api.deps import get_current_user, get_db_session, normalize_tenant_id
from zellovest_agentic.services.rag_llm import answer_question, generate_questions, judge_answer
from zellovest_agentic.services.tracing import trace_span
from zellovest_agentic.schemas.rag import (
    DocumentChunk,
    DocumentSearchRequest,
    DocumentSearchResponse,
    DocumentUploadRequest,
    DocumentUploadResponse,
    RAGEvaluationRequest,
    RAGEvaluationResult,
)
from zellovest_shared.db.models import RAGEvaluationRecord, User
from zellovest_shared.logging_conf import get_logger
from zellovest_shared.rag import sample_indexed_contexts, search_documents as retrieve_documents

logger = get_logger(__name__)
router = APIRouter(prefix="/rag", tags=["rag"])


@router.post("/search", response_model=DocumentSearchResponse)
async def search_documents(
    body: DocumentSearchRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> DocumentSearchResponse:
    """Search tenant-indexed documents using dense and sparse retrieval."""
    del session
    tenant_id = normalize_tenant_id(current_user.tenant_id)
    if body.tenant_id and normalize_tenant_id(body.tenant_id) != tenant_id:
        raise HTTPException(status_code=403, detail="tenant context mismatch")
    if body.date_from or body.date_to:
        raise HTTPException(status_code=422, detail="date filtering is not supported for indexed passages yet")
    started = time.perf_counter()
    request_id = request.state.request_id
    try:
        with trace_span("rag.hybrid_search", {"request_id": request_id,
                                              "tenant_id": tenant_id,
                                              "vendor_filter": bool(body.vendor_id),
                                              "document_type": body.document_type,
                                              "limit": body.limit}) as span:
            rows = await asyncio.to_thread(
                retrieve_documents, tenant_id=tenant_id, query=body.query,
                vendor_id=body.vendor_id,
                document_type=(
                    "purchase_order" if body.document_type == "po" else body.document_type
                ),
                limit=body.limit,
            )
            if span:
                span.update(metadata={"result_count": len(rows),
                                      "latency_ms": int((time.perf_counter() - started) * 1000)})
    except Exception as exc:
        logger.error("rag_search_unavailable", request_id=request_id, tenant_id=tenant_id,
                     error_class=type(exc).__name__)
        raise HTTPException(status_code=503, detail="document search is temporarily unavailable") from exc
    logger.info("document_search_completed", request_id=request_id, tenant_id=tenant_id,
                result_count=len(rows),
                elapsed_ms=int((time.perf_counter() - started) * 1000))
    chunks = [DocumentChunk(
        chunk_id=str(row.get("chunk_id", "")), document_id=str(row.get("document_id", "")),
        document_type=str(row.get("document_type", "other")),
        vendor_id=str(row["vendor_id"]) if row.get("vendor_id") else None,
        page=row.get("page"), section=row.get("section"), content=str(row.get("content", "")),
        score=float(row.get("score", 0.0)),
        provenance={"filename": row.get("filename"), "parent_id": row.get("parent_id"),
                    "bbox": row.get("bbox")},
    ) for row in rows]
    return DocumentSearchResponse(
        query=body.query,
        chunks=chunks,
        total_results=len(chunks),
        search_time_ms=int((time.perf_counter() - started) * 1000),
    )


@router.post("/upload", response_model=DocumentUploadResponse)
async def upload_document(
    body: DocumentUploadRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> DocumentUploadResponse:
    """Reject direct content upload; documents must use the audited upload pipeline."""
    del session
    if body.tenant_id and normalize_tenant_id(body.tenant_id) != normalize_tenant_id(current_user.tenant_id):
        raise HTTPException(status_code=403, detail="tenant context mismatch")
    raise HTTPException(status_code=status.HTTP_410_GONE,
                         detail="Use the document upload pipeline to preserve provenance")


@router.get("/documents/{document_id}/chunks", response_model=list[DocumentChunk])
async def get_document_chunks(
    document_id: str,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> list[DocumentChunk]:
    """Return not found until paginated document chunk inspection is implemented."""
    del current_user, session
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"Document {document_id} not found",
    )


@router.get("/documents/{document_id}/pages/{page_number}", response_model=DocumentChunk | None)
async def get_document_page(
    document_id: str,
    page_number: int,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> DocumentChunk | None:
    """Return not found for unavailable page-level detail."""
    del current_user, session
    raise HTTPException(status_code=404, detail=f"Document {document_id} page {page_number} not found")


@router.post("/evaluate", response_model=RAGEvaluationResult)
async def evaluate_rag(
    body: RAGEvaluationRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> RAGEvaluationResult:
    """Generate questions from indexed contract passages and score RAG with an LLM judge."""
    tenant_id = normalize_tenant_id(current_user.tenant_id)
    if body.tenant_id and normalize_tenant_id(body.tenant_id) != tenant_id:
        raise HTTPException(status_code=403, detail="tenant context mismatch")
    try:
        contexts = await asyncio.to_thread(sample_indexed_contexts,
                                           tenant_id=tenant_id, limit=body.sample_size,
                                           vendor_id=body.vendor_id)
        if not contexts:
            raise HTTPException(status_code=409, detail="no indexed contract passages to evaluate")
        results: list[dict[str, object]] = []
        for context in contexts[:body.sample_size]:
            source_text = str(context.get("parent_content") or context.get("content") or "")
            questions = await asyncio.to_thread(generate_questions, source_text,
                                                 body.questions_per_passage)
            for question in questions:
                retrieved = await asyncio.to_thread(
                    retrieve_documents, tenant_id=tenant_id, query=question,
                    vendor_id=body.vendor_id,
                    document_type=str(context.get("document_type") or "contract"), limit=6,
                )
                generated = await asyncio.to_thread(answer_question, question, retrieved)
                with trace_span("rag.llm_judge", {"tenant_id": tenant_id,
                                                   "source_document_id": context.get("document_id"),
                                                   "retrieved_count": len(retrieved)}):
                    scores = await asyncio.to_thread(judge_answer, question,
                                                     generated["answer"], retrieved, source_text)
                results.append({
                    "question_hash": hashlib.sha256(
                        f"{context.get('document_id', '')}:{question}".encode()
                    ).hexdigest()[:16],
                    "source_document_id": str(context.get("document_id", "")),
                    **{key: scores[key] for key in
                       ("relevance", "faithfulness", "citation_support")},
                    "context_coverage": scores["context_coverage"],
                })
        if not results:
            raise HTTPException(status_code=502, detail="question generation returned no questions")
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("rag_evaluation_failed", tenant_id=tenant_id,
                     error_class=type(exc).__name__)
        raise HTTPException(status_code=503, detail="RAG evaluation is temporarily unavailable") from exc
    count = len(results)
    from zellovest_agentic.config import get_agentic_reasoning_settings

    configured_settings = get_agentic_reasoning_settings()
    evaluator_model = (
        configured_settings.rag_evaluator_model
        or (
            configured_settings.groq_model
            if configured_settings.groq_api_key
            else os.getenv("LLM_MODEL", configured_settings.llm_model)
        )
    )
    run_id = uuid4()
    for item in results:
        session.add(RAGEvaluationRecord(
            tenant_id=tenant_id,
            run_id=run_id,
            evaluator_model=evaluator_model,
            question_hash=str(item["question_hash"]),
            source_document_id=UUID(str(item["source_document_id"])),
            scores={key: item[key] for key in
                    ("relevance", "faithfulness", "citation_support", "context_coverage")},
        ))
    await session.commit()
    with trace_span("rag.evaluation_run", {"tenant_id": tenant_id,
                                           "evaluated_questions": count,
                                           "sample_size": len(contexts)}):
        pass
    return RAGEvaluationResult(
        run_id=run_id,
        evaluator_model=evaluator_model,
        evaluated_questions=count,
        mean_relevance=sum(float(item["relevance"]) for item in results) / count,
        mean_faithfulness=sum(float(item["faithfulness"]) for item in results) / count,
        mean_citation_support=sum(float(item["citation_support"]) for item in results) / count,
        mean_context_coverage=sum(float(item["context_coverage"]) for item in results) / count,
        results=results,
    )
