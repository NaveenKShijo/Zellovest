"""Bounded, evidence-first reconciliation investigation agent.

This agent is intentionally not an autonomous financial decision-maker. It
travels only through MCP tools, preserves deterministic AP-audit results, and
keeps facts, calculations, hypotheses, and review requests separate.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from zellovest_shared.logging_conf import get_logger

from zellovest_agentic.mcp.client import McpHostError, McpIdentity
from zellovest_agentic.mcp.pool import McpPool
from zellovest_agentic.schemas.investigation import (
    InvestigationCitation,
    InvestigationDataGap,
    InvestigationFinding,
    InvestigationToolTrace,
    ReconciliationInvestigationResponse,
)

logger = get_logger(__name__)


def _citation(
    tool: str,
    *,
    source_id: str | None = None,
    document_id: str | None = None,
    page: int | None = None,
    section: str | None = None,
    excerpt: str | None = None,
) -> InvestigationCitation:
    """Create one compact, source-preserving citation."""
    return InvestigationCitation(
        tool=tool,
        source_id=source_id,
        document_id=document_id,
        page=page,
        section=section,
        excerpt=excerpt[:500] if excerpt else None,
    )


class ProcurementInvestigationAgent:
    """Explain an AP exception by following its linked commercial evidence."""

    def __init__(self, pool: McpPool) -> None:
        """Store the MCP-only capability boundary for investigations."""
        self.pool = pool

    async def _call(
        self,
        tool: str,
        arguments: dict[str, Any],
        identity: McpIdentity,
        *,
        purpose: str,
        gaps: list[InvestigationDataGap],
        trace: list[InvestigationToolTrace],
    ) -> dict[str, Any] | None:
        """Call one read-only tool and surface controlled failures as data gaps."""
        try:
            result = await self.pool.call_tool(tool, arguments, identity, purpose=purpose)
        except McpHostError as exc:
            gaps.append(InvestigationDataGap(tool=tool, code=exc.code, message=exc.message))
            trace.append(InvestigationToolTrace(tool=tool, success=False))
            logger.info(
                "procurement_investigation_tool_unavailable",
                tenant_id=identity.tenant_id,
                correlation_id=identity.correlation_id,
                tool=tool,
                code=exc.code,
            )
            return None
        summary = str(result.data.get("summary") or "").strip() or None
        trace.append(InvestigationToolTrace(tool=tool, success=True, result_summary=summary))
        return result.data

    async def investigate(
        self, exception_id: str, identity: McpIdentity
    ) -> ReconciliationInvestigationResponse:
        """Traverse source records and return a non-autonomous explanation.

        The sequence intentionally mirrors PRD #13: exception/invoice -> contract
        and PO -> deterministic comparison -> prior invoices and card spend ->
        contract versions/amendments. Each tool remains tenant-scoped by MCP.
        """
        gaps: list[InvestigationDataGap] = []
        trace: list[InvestigationToolTrace] = []
        facts: list[InvestigationFinding] = []
        calculations: list[InvestigationFinding] = []
        hypotheses: list[InvestigationFinding] = []
        review: list[InvestigationFinding] = []
        citations: list[InvestigationCitation] = []

        root = await self._call(
            "get_reconciliation_exception",
            {"exception_id": exception_id},
            identity,
            purpose="linked invoice, contract, PO, and deterministic exception",
            gaps=gaps,
            trace=trace,
        )
        if root is None:
            return ReconciliationInvestigationResponse(
                exception_id=exception_id,
                summary=(
                    "The investigation could not load its authoritative reconciliation exception."
                ),
                needs_human_review=[
                    InvestigationFinding(
                        statement=(
                            "Retry after the reconciliation record is available; "
                            "no conclusion was drawn."
                        )
                    )
                ],
                data_gaps=gaps,
                tool_trace=trace,
                generated_at=datetime.now(UTC),
            )

        exception = root.get("exception") if isinstance(root.get("exception"), dict) else {}
        invoice = root.get("invoice") if isinstance(root.get("invoice"), dict) else {}
        contract = root.get("contract") if isinstance(root.get("contract"), dict) else {}
        term = root.get("term") if isinstance(root.get("term"), dict) else {}
        purchase_order = (
            root.get("purchase_order") if isinstance(root.get("purchase_order"), dict) else None
        )
        root_citation = _citation(
            "get_reconciliation_exception",
            source_id=str(exception.get("id") or exception_id),
        )
        citations.append(root_citation)

        invoice_number = invoice.get("invoice_number") or "the linked invoice"
        vendor_name = invoice.get("vendor_name") or contract.get("vendor_name") or "the vendor"
        facts.append(
            InvestigationFinding(
                statement=(
                    f"{invoice_number} is linked to {vendor_name}, contract "
                    f"{contract.get('contract_number') or 'not recorded'}, and rule "
                    f"{exception.get('rule_type') or 'not recorded'}."
                ),
                citations=[root_citation],
            )
        )
        if purchase_order:
            facts.append(
                InvestigationFinding(
                    statement=(
                        f"The exception is linked to purchase order "
                        f"{purchase_order.get('po_number') or purchase_order.get('id')}."
                    ),
                    citations=[root_citation],
                )
            )
        else:
            review.append(
                InvestigationFinding(
                    statement=(
                        "No linked purchase order was returned; verify whether an "
                        "approved PO exists outside the record linkage."
                    ),
                    citations=[root_citation],
                )
            )

        expected = exception.get("expected_value")
        billed = exception.get("billed_value")
        variance = exception.get("variance_amount")
        if expected is not None and billed is not None:
            variance_text = variance if variance is not None else "unavailable"
            variance_pct = exception.get("variance_pct")
            variance_pct_text = (
                variance_pct if variance_pct is not None else "percentage unavailable"
            )
            calculations.append(
                InvestigationFinding(
                    statement=(
                        f"The AP audit calculated billed value {billed} versus "
                        f"expected value {expected}; recorded variance is "
                        f"{variance_text} ({variance_pct_text}%)."
                    ),
                    citations=[root_citation],
                )
            )

        invoice_id = invoice.get("id")
        comparison: dict[str, Any] | None = None
        if invoice_id:
            comparison = await self._call(
                "compare_invoice_contract",
                {"invoice_id": str(invoice_id), "contract_id": str(contract.get("id") or "")}
                if contract.get("id")
                else {"invoice_id": str(invoice_id)},
                identity,
                purpose="deterministic invoice-to-contract comparison",
                gaps=gaps,
                trace=trace,
            )
        else:
            review.append(
                InvestigationFinding(
                    statement=(
                        "The exception did not return an invoice identifier, so a fresh "
                        "line-by-line comparison could not run."
                    ),
                    citations=[root_citation],
                )
            )

        if comparison:
            comparison_citation = _citation(
                "compare_invoice_contract",
                source_id=str(comparison.get("invoice_id") or invoice_id),
            )
            citations.append(comparison_citation)
            for line in comparison.get("lines", [])[:20]:
                if not isinstance(line, dict):
                    continue
                if line.get("matched") is False:
                    line_number = line.get("line_no")
                    description = line.get("description") or "unlabelled"
                    review.append(
                        InvestigationFinding(
                            statement=(
                                f"Invoice line {line_number} ({description}) "
                                "did not match a contract term."
                            ),
                            citations=[comparison_citation],
                        )
                    )
                    continue
                line_number = line.get("line_no")
                quantity = line.get("quantity")
                billed_price = line.get("billed_unit_price")
                contract_price = line.get("contract_unit_price")
                line_variance = line.get("variance_amount")
                calculations.append(
                    InvestigationFinding(
                        statement=(
                            f"Invoice line {line_number} billed {quantity} units at "
                            f"{billed_price}; the comparison matched contract price "
                            f"{contract_price} with line variance {line_variance}"
                        ),
                        citations=[comparison_citation],
                    )
                )
            for finding in comparison.get("findings", [])[:20]:
                if not isinstance(finding, dict):
                    continue
                finding_text = finding.get("message") or finding.get("code")
                review.append(
                    InvestigationFinding(
                        statement=f"Deterministic comparison finding: {finding_text}",
                        citations=[comparison_citation],
                    )
                )

        vendor_id = invoice.get("vendor_id") or contract.get("vendor_id")
        contract_id = contract.get("id") or invoice.get("contract_id")
        history: dict[str, Any] | None = None
        if vendor_id:
            invoice_date = str(invoice.get("invoice_date") or "")
            history_args: dict[str, Any] = {"vendor_id": str(vendor_id), "limit": 20}
            if contract_id:
                history_args["contract_id"] = str(contract_id)
            if invoice_date:
                history_args["before_date"] = invoice_date[:10]
            history = await self._call(
                "get_vendor_commercial_history",
                history_args,
                identity,
                purpose="prior invoices, card transactions, amendments, and renewal lineage",
                gaps=gaps,
                trace=trace,
            )
        else:
            review.append(
                InvestigationFinding(
                    statement=(
                        "No vendor identifier was available for historical invoice and "
                        "card-transaction retrieval."
                    ),
                    citations=[root_citation],
                )
            )

        if history:
            history_citation = _citation(
                "get_vendor_commercial_history",
                source_id=str(history.get("contract_id") or history.get("vendor_id") or "") or None,
            )
            citations.append(history_citation)
            prior_invoices = (
                history.get("invoices") if isinstance(history.get("invoices"), list) else []
            )
            card_transactions = (
                history.get("card_transactions")
                if isinstance(history.get("card_transactions"), list)
                else []
            )
            versions = (
                history.get("contract_versions")
                if isinstance(history.get("contract_versions"), list)
                else []
            )
            facts.append(
                InvestigationFinding(
                    statement=(
                        f"The commercial-history lookup returned {len(prior_invoices)} "
                        f"prior invoice(s), {len(card_transactions)} vendor-linked card "
                        f"transaction(s), and {len(versions)} "
                        "contract version(s)."
                    ),
                    citations=[history_citation],
                )
            )
            if not prior_invoices:
                review.append(
                    InvestigationFinding(
                        statement=(
                            "No prior invoices were returned for the requested contract and "
                            "date window; this is unavailable history, not proof of no "
                            "prior billing."
                        ),
                        citations=[history_citation],
                    )
                )
            if not card_transactions:
                review.append(
                    InvestigationFinding(
                        statement=(
                            "No vendor-linked card transactions were returned; transactions "
                            "without a resolved vendor link may require separate review."
                        ),
                        citations=[history_citation],
                    )
                )

            target_line_id = term.get("contract_line_id")
            matching_terms = [
                item
                for item in history.get("term_history", [])
                if isinstance(item, dict)
                and (not target_line_id or item.get("contract_line_id") == target_line_id)
            ]
            if matching_terms:
                facts.append(
                    InvestigationFinding(
                        statement=(
                            f"The linked commercial line has {len(matching_terms)} versioned "
                            "term record(s); their effective dates and quantity bounds are "
                            "preserved as contract history."
                        ),
                        citations=[history_citation],
                    )
                )
                for prior_term in matching_terms[-5:]:
                    if prior_term.get("id") == term.get("id"):
                        continue
                    hypotheses.append(
                        InvestigationFinding(
                            statement=(
                                "A different recorded term version has unit price "
                                f"{prior_term.get('unit_price')} and quantity bounds "
                                f"{prior_term.get('qty_min')}-{prior_term.get('qty_max')} "
                                f"effective {prior_term.get('effective_from')} to "
                                f"{prior_term.get('effective_to') or 'open-ended'}. "
                                "Confirm whether it applies "
                                "to this billed line."
                            ),
                            citations=[history_citation],
                        )
                    )

        if vendor_id:
            amendment_subject = term.get("product_code") or term.get("description") or vendor_name
            amendment_search = await self._call(
                "search_documents",
                {
                    "query": f"amendment pricing seats {amendment_subject}"[:2000],
                    "vendor_id": str(vendor_id),
                    "document_type": "amendment",
                    "limit": 5,
                },
                identity,
                purpose="source amendment passages and page provenance",
                gaps=gaps,
                trace=trace,
            )
            if amendment_search:
                chunks = (
                    amendment_search.get("chunks")
                    if isinstance(amendment_search.get("chunks"), list)
                    else []
                )
                for chunk in chunks[:5]:
                    if not isinstance(chunk, dict):
                        continue
                    citation = _citation(
                        "search_documents",
                        source_id=str(chunk.get("chunk_id") or "") or None,
                        document_id=str(chunk.get("document_id") or "") or None,
                        page=chunk.get("page") if isinstance(chunk.get("page"), int) else None,
                        section=str(chunk.get("section") or "") or None,
                        excerpt=str(chunk.get("content") or chunk.get("parent_content") or ""),
                    )
                    citations.append(citation)
                    hypotheses.append(
                        InvestigationFinding(
                            statement=(
                                "This amendment passage may explain a price or seat-tier "
                                "change; confirm its effective scope against the linked invoice "
                                "line before treating it as an approved charge."
                            ),
                            citations=[citation],
                        )
                    )
                if not chunks:
                    review.append(
                        InvestigationFinding(
                            statement=(
                                "No indexed amendment passage was returned; verify that "
                                "amendments were uploaded and extracted."
                            ),
                        )
                    )

        summary = (
            f"Investigation of {invoice_number}: {len(facts)} confirmed fact(s), "
            f"{len(calculations)} deterministic calculation(s), and "
            f"{len(review)} item(s) requiring review. "
            "This result does not approve payment, credit, or contract changes."
        )
        return ReconciliationInvestigationResponse(
            exception_id=exception_id,
            summary=summary,
            confirmed_facts=facts,
            calculated_values=calculations,
            possible_explanations=hypotheses,
            needs_human_review=review,
            citations=citations,
            data_gaps=gaps,
            tool_trace=trace,
            generated_at=datetime.now(UTC),
        )
