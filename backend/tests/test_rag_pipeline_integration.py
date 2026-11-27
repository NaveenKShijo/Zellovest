"""Integration checks for planner scope, evidence, and migration verification."""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager, nullcontext
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError
from zellovest_agentic.agent.executor import ExecutionResult, _document_evidence
from zellovest_agentic.agent.planner import AgentPlanner
from zellovest_agentic.agent.synthesizer import AnswerSynthesizer, _evidence_payload
from zellovest_agentic.api.routers import rag as rag_api
from zellovest_agentic.config import AgenticReasoningSettings
from zellovest_agentic.mcp.registry import ToolRegistry
from zellovest_agentic.schemas.rag import DocumentSearchRequest
from zellovest_shared.mcp_contracts import PROCUREMENT_ROLE
from zellovest_shared.rag import retain_existing_documents

import rag_reindex
from rag_reindex import compare_index


def test_planner_preserves_explicit_vendor_and_document(monkeypatch: pytest.MonkeyPatch) -> None:
    """Model-selected filters cannot override or drop explicit client context."""
    vendor = str(uuid.uuid4())
    document = str(uuid.uuid4())
    other = str(uuid.uuid4())
    monkeypatch.setattr(
        "zellovest_agentic.agent.planner.complete_json",
        lambda *args, **kwargs: {"steps": [{"tool": "search_contracts", "arguments": {
            "query": "renewal", "vendor_id": other, "vendor_name": "Wrong vendor"}}]},
    )
    plan = AgentPlanner().plan(question="renewal", context={"vendor_id": vendor,
                               "document_id": document}, history=[],
                               registry=ToolRegistry(PROCUREMENT_ROLE))
    assert plan.steps[0].arguments["vendor_id"] == vendor
    assert plan.steps[0].arguments["document_id"] == document
    assert "vendor_name" not in plan.steps[0].arguments


def test_fallback_decomposes_questions_with_bounded_scoped_steps() -> None:
    """Independent clause questions get separate, explicitly scoped searches."""
    vendor = str(uuid.uuid4())
    plan = AgentPlanner(enabled=False, max_steps=3).plan(
        question="What is the notice period? What is the termination clause?",
        context={"vendor_id": vendor}, history=[], registry=ToolRegistry(PROCUREMENT_ROLE),
    )
    searches = [step for step in plan.steps if step.tool == "search_contracts"]
    assert len(plan.steps) <= 3 and len(searches) == 2
    assert searches[0].arguments["query"] != searches[1].arguments["query"]
    assert all(step.arguments["vendor_id"] == vendor for step in searches)


def test_synthesis_uses_parent_context_and_rejects_uncited_claims() -> None:
    """The model receives page-specific parent context while citations use the child."""
    chunks = {"chunks": [{"document_id": "doc", "chunk_id": "chunk", "page": 3,
                          "filename": "agreement.pdf", "parent_id": "parent",
                          "content": "Thirty days", "parent_content": "Full source context",
                          "adjacent_context": [{"page": 4, "parent_id": "next",
                                                "section": "RENEWAL", "content": "Next page"}]}]}
    items = _document_evidence("search_documents", "mcp-2-documents", chunks, 0)
    execution = ExecutionResult(evidence=items)
    payload, _, _ = _evidence_payload(execution, 4000)
    assert payload[0]["passage"] == "Full source context"
    assert payload[0]["excerpt"] == "Thirty days"
    assert payload[1]["page"] == 4 and payload[1]["passage"] == "Next page"
    assert "source_context" not in items[0].model_dump()
    synthesizer = AnswerSynthesizer(AgenticReasoningSettings(), enabled=False)
    answer = synthesizer._from_candidate({"answer": "Unverified claim", "citations": ["fake"]},
                                         execution, allowed_ids={"ev-0"})
    assert answer.source == "deterministic"
    assert "Unverified claim" not in answer.answer
    cited = synthesizer._from_candidate({"answer": "Next page", "citations": ["ev-1"]},
                                        execution, allowed_ids={"ev-0", "ev-1"})
    assert cited.citations[0].evidence_id == "ev-1" and cited.citations[0].page == 4


def test_reindex_comparison_checks_parent_and_child_integrity() -> None:
    """Correct fingerprints alone do not hide missing parents or children."""
    healthy = {"versions": {("g", "v")}, "children": 2, "parents": {"p"},
               "references": {"p"}, "adjacent_references": set(),
               "expected_children": {2}, "expected_parents": {1}}
    assert not any(compare_index({"d": "v"}, {"d": healthy}).values())
    damaged = {**healthy, "parents": set()}
    assert compare_index({"d": "v"}, {"d": damaged})["stale"] == ["d"]


def test_reindex_enumerates_only_eligible_tenant_documents(monkeypatch: pytest.MonkeyPatch) -> None:
    """Backfill discovery honors tenant, upload status, and artifact availability."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from zellovest_shared.db.core import Vendor
    from zellovest_shared.db.models import Base, ExtractionArtifact, Upload, UploadStatus
    from zellovest_shared.db.transact import DocStatus, DocType, Document

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    vendor_id = uuid.uuid4()
    document_id = uuid.uuid4()
    upload_id = uuid.uuid4()
    with Session(engine) as session:
        session.add(Vendor(id=vendor_id, tenant_id="tenant-a", name="Acme"))
        session.add(Upload(id=upload_id, tenant_id="tenant-a", filename="a.pdf",
                           gcs_key="raw/a.pdf", mime_type="application/pdf",
                           size_expected=100, document_type="contract", status=UploadStatus.COMPLETED))
        session.add(Document(id=document_id, tenant_id="tenant-a", vendor_id=vendor_id,
                             upload_id=upload_id, filename="a.pdf", gcs_key="raw/a.pdf",
                             document_type=DocType.CONTRACT, status=DocStatus.EXTRACTED,
                             mime_type="application/pdf"))
        session.add(ExtractionArtifact(tenant_id="tenant-a", upload_id=upload_id,
                                       source_gcs_key="raw/a.pdf", artifact_gcs_key="artifact/a"))
        session.commit()
    monkeypatch.setattr(rag_reindex, "get_sync_engine", lambda: engine)
    try:
        assert list(rag_reindex.expected_documents("tenant-a")) == [str(document_id)]
        assert not rag_reindex.expected_documents("tenant-b")
    finally:
        engine.dispose()


@pytest.mark.asyncio
async def test_search_api_forwards_identity_and_date_filters_via_mcp(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Direct search retains authenticated tenant scope and uses the MCP boundary."""
    document_id = uuid.uuid4()
    user = SimpleNamespace(tenant_id="tenant-a", id=uuid.uuid4(), role=PROCUREMENT_ROLE,
                           email="user@example.test")
    pool = SimpleNamespace(call_tool=AsyncMock(return_value=SimpleNamespace(data={"chunks": []})))
    monkeypatch.setattr(rag_api, "trace_span", lambda *args, **kwargs: nullcontext(None))
    request = SimpleNamespace(state=SimpleNamespace(request_id="request-id"),
                              app=SimpleNamespace(state=SimpleNamespace(mcp_pool=pool)))
    body = DocumentSearchRequest(query="renewal", document_id=document_id,
                                 date_from="2024-01-01", date_to="2024-12-31")
    response = await rag_api.search_documents(body, request, user, None)
    assert response.total_results == 0
    call = pool.call_tool.await_args
    assert call.args[0] == "search_document_chunks"
    assert call.args[1]["date_from"] == "2024-01-01"
    assert call.args[1]["document_id"] == str(document_id)
    assert call.args[2].tenant_id == "tenant-a"
    with pytest.raises(ValidationError):
        DocumentSearchRequest(query="q", date_from="2024-02-01", date_to="2024-01-01")


@pytest.mark.asyncio
async def test_deleted_documents_are_excluded_before_returning_evidence() -> None:
    """Pending or failed Qdrant cleanup cannot expose a deleted source."""
    allowed = uuid.uuid4()
    deleted = uuid.uuid4()
    session = SimpleNamespace(scalars=AsyncMock(return_value=SimpleNamespace(all=lambda: [allowed])))
    rows = [{"document_id": str(allowed)}, {"document_id": str(deleted)}]
    result = await retain_existing_documents(session, tenant_id="tenant-a", rows=rows)
    assert result == [rows[0]]
    statement = session.scalars.await_args.args[0]
    assert "tenant_id" in str(statement)
    assert "tenant-a" in statement.compile().params.values()


@pytest.mark.asyncio
async def test_ambiguous_vendor_does_not_fall_back_to_unfiltered_search(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unresolved vendor is an explicit gap, never an unscoped search."""
    from zellovest_mcp import documents
    from zellovest_mcp.errors import ToolError

    empty = SimpleNamespace(all=list)
    ambiguous = SimpleNamespace(all=lambda: [object(), object()])
    session = SimpleNamespace(scalars=AsyncMock(side_effect=[empty, ambiguous]))

    @asynccontextmanager
    async def fake_session():
        """Yield deterministic vendor lookup results."""
        yield session

    search = MagicMock()
    monkeypatch.setattr(documents, "async_session_context", fake_session)
    monkeypatch.setattr(documents, "rag_search_documents", search)
    with pytest.raises(ToolError):
        await documents._semantic_search(SimpleNamespace(tenant_id="t"), query="renewal",
                                         vendor_id=None, vendor_name="Acme", limit=5)
    search.assert_not_called()


@pytest.mark.asyncio
async def test_document_service_resolves_tenant_vendor_and_date_filters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Resolve names and date-added ranges in the owning tenant's database."""
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from zellovest_mcp import documents
    from zellovest_shared.db.core import Vendor
    from zellovest_shared.db.models import Base
    from zellovest_shared.db.transact import DocStatus, DocType, Document

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    vendor_a, vendor_b, doc_a, doc_late, doc_b = [uuid.uuid4() for _ in range(5)]
    async with maker() as session:
        session.add_all([Vendor(id=vendor_a, tenant_id="tenant-a", name="Acme"),
                         Vendor(id=vendor_b, tenant_id="tenant-b", name="Acme")])
        for doc_id, tenant, vendor_id, added in (
            (doc_a, "tenant-a", vendor_a, datetime(2024, 1, 12, tzinfo=UTC)),
            (doc_late, "tenant-a", vendor_a, datetime(2024, 2, 2, tzinfo=UTC)),
            (doc_b, "tenant-b", vendor_b, datetime(2024, 1, 12, tzinfo=UTC)),
        ):
            session.add(Document(id=doc_id, tenant_id=tenant, vendor_id=vendor_id,
                                 filename="doc.pdf", gcs_key=f"docs/{doc_id}",
                                 document_type=DocType.CONTRACT, status=DocStatus.EXTRACTED,
                                 mime_type="application/pdf", created_at=added))
        await session.commit()

    @asynccontextmanager
    async def fake_session():
        """Yield a fresh session against the isolated database."""
        async with maker() as session:
            yield session

    observed = {}

    def fake_search(**kwargs):
        """Return a matching child while recording the generated filters."""
        observed.update(kwargs)
        return [{"tenant_id": "tenant-a", "document_id": str(doc_a),
                 "chunk_id": "chunk", "content": "source", "page": 1}]

    monkeypatch.setattr(documents, "async_session_context", fake_session)
    monkeypatch.setattr(documents, "rag_search_documents", fake_search)
    try:
        rows = await documents._semantic_search(
            SimpleNamespace(tenant_id="tenant-a"), query="notice", vendor_id=None,
            vendor_name="Acme", date_from="2024-01-01", date_to="2024-01-31", limit=5,
        )
        assert len(rows) == 1
        assert observed["vendor_id"] == str(vendor_a)
        assert observed["document_ids"] == [str(doc_a)]
    finally:
        await engine.dispose()
