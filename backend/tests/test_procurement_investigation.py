"""Tests for the MCP-only Procurement Investigation Agent."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from zellovest_agentic.agent.investigation import ProcurementInvestigationAgent
from zellovest_agentic.mcp.client import McpHostError, McpIdentity, McpToolResult


def _tool_result(tool: str, data: dict[str, Any]) -> McpToolResult:
    """Build a successful read-only MCP result for a test fixture."""
    return McpToolResult(
        server="mcp-1-procurement",
        tool=tool,
        tool_version="1.0.0",
        risk_class="read_only",
        operation="read",
        data=data,
        latency_ms=1,
        attempts=1,
        correlation_id="test-correlation",
        arguments_digest="test-digest",
        result_size=1,
    )


class _FakePool:
    """Small MCP pool fake keyed by tool name."""

    def __init__(self, responses: dict[str, dict[str, Any] | Exception]) -> None:
        """Store fixture responses without bypassing the agent tool boundary."""
        self.responses = responses
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def call_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        identity: McpIdentity,
        *,
        purpose: str | None = None,
    ) -> McpToolResult:
        """Record the bounded tool call and return its prepared response."""
        del identity, purpose
        self.calls.append((tool_name, arguments))
        response = self.responses[tool_name]
        if isinstance(response, Exception):
            raise response
        return _tool_result(tool_name, response)


@pytest.mark.asyncio
async def test_investigation_separates_evidence_categories_and_traverses_history():
    """Investigation uses the PRD traversal without approving a financial action."""
    exception_id = str(uuid.uuid4())
    invoice_id = str(uuid.uuid4())
    contract_id = str(uuid.uuid4())
    vendor_id = str(uuid.uuid4())
    term_id = str(uuid.uuid4())
    line_id = str(uuid.uuid4())
    pool = _FakePool(
        {
            "get_reconciliation_exception": {
                "exception": {
                    "id": exception_id,
                    "rule_type": "price",
                    "expected_value": 120.0,
                    "billed_value": 140.0,
                    "variance_amount": 300.0,
                    "variance_pct": 16.67,
                },
                "invoice": {
                    "id": invoice_id,
                    "invoice_number": "INV-23891",
                    "vendor_id": vendor_id,
                    "vendor_name": "Example SaaS",
                    "contract_id": contract_id,
                    "invoice_date": "2026-07-31T00:00:00+00:00",
                },
                "contract": {
                    "id": contract_id,
                    "vendor_id": vendor_id,
                    "contract_number": "CTR-01",
                },
                "term": {"id": term_id, "contract_line_id": line_id, "product_code": "SEAT"},
                "purchase_order": {"id": str(uuid.uuid4()), "po_number": "PO-44"},
            },
            "compare_invoice_contract": {
                "invoice_id": invoice_id,
                "lines": [
                    {
                        "line_no": 1,
                        "matched": True,
                        "quantity": "35",
                        "billed_unit_price": "140",
                        "contract_unit_price": "120",
                        "variance_amount": "700",
                    }
                ],
                "findings": [
                    {
                        "code": "quantity_out_of_bounds",
                        "message": "billed quantity 35 exceeds amendment maximum 20",
                    }
                ],
            },
            "get_vendor_commercial_history": {
                "vendor_id": vendor_id,
                "contract_id": contract_id,
                "invoices": [{"id": str(uuid.uuid4()), "invoice_number": "INV-OLD"}],
                "card_transactions": [],
                "contract_versions": [{"version_no": 1}, {"version_no": 2}],
                "term_history": [
                    {"id": str(uuid.uuid4()), "contract_line_id": line_id, "unit_price": "120"},
                    {
                        "id": term_id,
                        "contract_line_id": line_id,
                        "unit_price": "140",
                        "qty_min": "20",
                        "qty_max": "20",
                    },
                ],
            },
            "search_documents": {
                "chunks": [
                    {
                        "chunk_id": "chunk-1",
                        "document_id": str(uuid.uuid4()),
                        "page": 7,
                        "section": "Pricing amendment",
                        "content": "Additional seats are priced at $140 for a 20-seat tier.",
                    }
                ]
            },
        }
    )
    identity = McpIdentity(
        tenant_id="investigation-test",
        actor_id=str(uuid.uuid4()),
        role="procurement_member",
        correlation_id="test-correlation",
    )

    response = await ProcurementInvestigationAgent(pool).investigate(exception_id, identity)

    assert response.confirmed_facts
    assert response.calculated_values
    assert response.possible_explanations
    assert response.needs_human_review
    assert any("35" in item.statement for item in response.calculated_values)
    assert any("20" in item.statement for item in response.possible_explanations)
    assert "does not approve payment" in response.summary
    assert [call[0] for call in pool.calls] == [
        "get_reconciliation_exception",
        "compare_invoice_contract",
        "get_vendor_commercial_history",
        "search_documents",
    ]


@pytest.mark.asyncio
async def test_investigation_reports_unavailable_source_without_claiming_zero():
    """A failed history lookup becomes a data gap and a human-review item."""
    exception_id = str(uuid.uuid4())
    pool = _FakePool(
        {
            "get_reconciliation_exception": {
                "exception": {"id": exception_id, "rule_type": "price"},
                "invoice": {"id": str(uuid.uuid4()), "vendor_id": str(uuid.uuid4())},
                "contract": {},
                "term": {},
                "purchase_order": None,
            },
            "compare_invoice_contract": {
                "invoice_id": str(uuid.uuid4()),
                "lines": [],
                "findings": [],
            },
            "get_vendor_commercial_history": McpHostError(
                "timeout", "commercial history timed out", tool="get_vendor_commercial_history"
            ),
            "search_documents": {"chunks": []},
        }
    )
    identity = McpIdentity(
        tenant_id="investigation-test",
        actor_id=str(uuid.uuid4()),
        role="procurement_member",
        correlation_id="test-correlation",
    )

    response = await ProcurementInvestigationAgent(pool).investigate(exception_id, identity)

    assert any(gap.tool == "get_vendor_commercial_history" for gap in response.data_gaps)
    assert any(
        "No vendor-linked card transactions" not in item.statement
        for item in response.needs_human_review
    )
