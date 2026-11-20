"""Canonical MCP tool contracts shared by the host and the three MCP servers.

The MCP SDK transmits tool name/description/input schema, but it does not
carry product concerns such as risk class, authorization scope, tenant
boundary, idempotency, or audit event type. Keeping those declarations in one
shared module (imported by the host *and* every server) prevents policy drift
between the provider and the consumer.

See ``PRD.md`` section 25.7 for the required contract fields.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

ToolRisk = Literal["read_only", "low_risk", "high_risk"]
ToolOperation = Literal["read", "write"]

MCP_PROCUREMENT = "mcp-1-procurement"
MCP_DOCUMENTS = "mcp-2-documents"
MCP_EXTERNAL = "mcp-3-external"

MCP_SERVERS: tuple[str, ...] = (MCP_PROCUREMENT, MCP_DOCUMENTS, MCP_EXTERNAL)

PROCUREMENT_ROLE = "procurement_member"

#: V1 has a single role. Every scope is granted to that role; the mapping is
#: kept explicit so granular RBAC can be introduced without changing tools.
SCOPES_BY_ROLE: dict[str, frozenset[str]] = {
    PROCUREMENT_ROLE: frozenset(
        {
            "procurement.vendor.read",
            "procurement.contract.read",
            "procurement.invoice.read",
            "procurement.purchase_order.read",
            "procurement.spend.read",
            "procurement.license.read",
            "procurement.renewal.read",
            "procurement.reconciliation.read",
            "procurement.maverick.read",
            "procurement.savings.read",
            "documents.read",
            "contracts.read",
            "invoices.read",
            "policies.read",
            "procurement.task.write",
            "procurement.renewal.write",
            "procurement.workflow.write",
            "external.slack.write",
            "external.email.write",
            "external.erp.write",
        }
    ),
}


@dataclass(frozen=True)
class ToolContract:
    """Declarative contract for one MCP tool (PRD 25.7)."""

    name: str
    server: str
    description: str
    input_schema: Mapping[str, Any]
    output_schema: Mapping[str, Any]
    auth_scope: str
    risk_class: ToolRisk
    operation: ToolOperation
    timeout_seconds: float = 20.0
    idempotent: bool = True
    tenant_scoped: bool = True
    roles: tuple[str, ...] = (PROCUREMENT_ROLE,)
    evidence_behavior: str = "records"
    audit_event_type: str = "mcp.tool.read"
    version: str = "1.0.0"

    @property
    def requires_confirmation(self) -> bool:
        """Return True when execution must follow explicit human confirmation."""
        return self.risk_class == "high_risk"

    @property
    def read_only(self) -> bool:
        """Return True for non-mutating tools."""
        return self.risk_class == "read_only"

    def as_metadata(self) -> dict[str, Any]:
        """Serialize the non-schema portion for discovery endpoints."""
        return {
            "name": self.name,
            "server": self.server,
            "description": self.description,
            "auth_scope": self.auth_scope,
            "roles": list(self.roles),
            "tenant_scoped": self.tenant_scoped,
            "operation": self.operation,
            "risk_class": self.risk_class,
            "timeout_seconds": self.timeout_seconds,
            "idempotent": self.idempotent,
            "requires_confirmation": self.requires_confirmation,
            "evidence_behavior": self.evidence_behavior,
            "audit_event_type": self.audit_event_type,
            "version": self.version,
        }

    def strict_input_schema(self) -> dict[str, Any]:
        """Return the input schema with unknown top-level keys rejected.

        Output schemas intentionally remain permissive so tools can append
        provenance, pagination, and freshness metadata without lying about the
        fields the host depends on.
        """
        schema = dict(self.input_schema)
        schema["additionalProperties"] = False
        return schema


def _object(
    properties: Mapping[str, Any],
    required: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Build a strict JSON-Schema object declaration."""
    return {
        "type": "object",
        "properties": dict(properties),
        "required": list(required),
    }


def _any_object() -> dict[str, Any]:
    """Bound an output schema that is intentionally free-form."""
    return {"type": "object", "additionalProperties": True}


def _nullable_object() -> dict[str, Any]:
    """Allow an optional free-form object in an output schema."""
    return {"type": ["object", "null"], "additionalProperties": True}


def _nullable_string() -> dict[str, Any]:
    """Allow an optional string in an output schema."""
    return {"type": ["string", "null"]}


_DATE = {"type": "string", "format": "date"}
_UUID = {"type": "string", "minLength": 1}
_IDEMPOTENCY = {"type": "string", "minLength": 8, "maxLength": 128}
_DRY_RUN = {"type": "boolean", "default": True}
_CONFIRM_TOKEN = {"type": "string", "minLength": 16}

_PROCUREMENT_TOOLS: tuple[ToolContract, ...] = (
    ToolContract(
        name="get_vendor",
        server=MCP_PROCUREMENT,
        description=(
            "Return the canonical vendor record plus contract, invoice, license, "
            "and document counts for one vendor."
        ),
        input_schema=_object(
            {
                "vendor_id": _UUID,
                "vendor_name": {"type": "string", "minLength": 1, "maxLength": 256},
                "domain": {"type": "string", "maxLength": 256},
            }
        ),
        output_schema=_object(
            {
                "vendor": _any_object(),
                "counts": _any_object(),
                "as_of": {"type": "string"},
            },
            ("vendor",),
        ),
        auth_scope="procurement.vendor.read",
        risk_class="read_only",
        operation="read",
        timeout_seconds=10.0,
    ),
    ToolContract(
        name="get_contract",
        server=MCP_PROCUREMENT,
        description=(
            "Return a contract header, vendor, current versioned commercial terms, "
            "and amendment lineage."
        ),
        input_schema=_object(
            {
                "contract_id": _UUID,
                "contract_number": {"type": "string", "maxLength": 128},
                "include_versions": {"type": "boolean", "default": True},
            }
        ),
        output_schema=_object(
            {"contract": _any_object(), "versions": {"type": "array"}}, ("contract",)
        ),
        auth_scope="procurement.contract.read",
        risk_class="read_only",
        operation="read",
        timeout_seconds=15.0,
    ),
    ToolContract(
        name="get_invoice",
        server=MCP_PROCUREMENT,
        description=(
            "Return one invoice header, its line items, vendor, and linked "
            "audit exceptions."
        ),
        input_schema=_object(
            {
                "invoice_id": _UUID,
                "invoice_number": {"type": "string", "maxLength": 128},
            }
        ),
        output_schema=_object(
            {"invoice": _any_object(), "line_items": {"type": "array"}}, ("invoice",)
        ),
        auth_scope="procurement.invoice.read",
        risk_class="read_only",
        operation="read",
        timeout_seconds=15.0,
    ),
    ToolContract(
        name="get_purchase_order",
        server=MCP_PROCUREMENT,
        description="Return one purchase order header, line items, vendor, and linked contract.",
        input_schema=_object(
            {"po_id": _UUID, "po_number": {"type": "string", "maxLength": 128}}
        ),
        output_schema=_object(
            {"purchase_order": _any_object(), "line_items": {"type": "array"}},
            ("purchase_order",),
        ),
        auth_scope="procurement.purchase_order.read",
        risk_class="read_only",
        operation="read",
        timeout_seconds=15.0,
    ),
    ToolContract(
        name="get_vendor_spend",
        server=MCP_PROCUREMENT,
        description=(
            "Return authoritative invoice and card spend for one vendor over an "
            "optional date range, with monthly breakdown and methodology."
        ),
        input_schema=_object(
            {
                "vendor_id": _UUID,
                "start_date": _DATE,
                "end_date": _DATE,
                "include": {
                    "type": "array",
                    "items": {"enum": ["invoices", "card_transactions"]},
                    "default": ["invoices", "card_transactions"],
                },
            },
            ("vendor_id",),
        ),
        output_schema=_object(
            {
                "vendor_id": {"type": "string"},
                "invoice_total": {"type": "number"},
                "card_total": {"type": "number"},
                "total_spend": {"type": "number"},
                "currency": {"type": "string"},
                "breakdown": {"type": "array"},
                "methodology": {"type": "string"},
            },
            ("vendor_id", "total_spend", "currency"),
        ),
        auth_scope="procurement.spend.read",
        risk_class="read_only",
        operation="read",
        timeout_seconds=20.0,
    ),
    ToolContract(
        name="get_license_usage",
        server=MCP_PROCUREMENT,
        description=(
            "Return purchased/assigned/active/inactive seat counts, utilization, "
            "recoverable spend, and the latest seat forecast for one vendor."
        ),
        input_schema=_object(
            {
                "vendor_id": _UUID,
                "inactive_days": {
                    "type": "integer",
                    "enum": [30, 60, 90],
                    "default": 30,
                },
            },
            ("vendor_id",),
        ),
        output_schema=_object(
            {
                "vendor_id": {"type": "string"},
                "assigned_seats": {"type": "integer"},
                "active_seats": {"type": "integer"},
                "inactive_seats": {"type": "integer"},
                "utilization_pct": {"type": "number"},
                "recoverable_annual_spend": {"type": "number"},
                "forecast": _nullable_object(),
            },
            ("vendor_id", "assigned_seats", "utilization_pct"),
        ),
        auth_scope="procurement.license.read",
        risk_class="read_only",
        operation="read",
        timeout_seconds=20.0,
    ),
    ToolContract(
        name="find_renewals",
        server=MCP_PROCUREMENT,
        description=(
            "Return upcoming contract renewals with notice deadlines, urgency "
            "badges, annual contract value, and measured seat utilization."
        ),
        input_schema=_object(
            {
                "days_ahead": {"type": "integer", "minimum": 1, "maximum": 730, "default": 120},
                "badge": {
                    "enum": ["all", "30d", "60d", "90d", "120d", "future"],
                    "default": "all",
                },
                "auto_renew_only": {"type": "boolean", "default": False},
                "vendor_id": _UUID,
                "limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 20},
            }
        ),
        output_schema=_object(
            {"renewals": {"type": "array"}, "count": {"type": "integer"}},
            ("renewals",),
        ),
        auth_scope="procurement.renewal.read",
        risk_class="read_only",
        operation="read",
        timeout_seconds=20.0,
    ),
    ToolContract(
        name="get_reconciliation_exception",
        server=MCP_PROCUREMENT,
        description=(
            "Return one immutable reconciliation exception with invoice, contract "
            "term, variance math, PO, and source document references."
        ),
        input_schema=_object({"exception_id": _UUID}, ("exception_id",)),
        output_schema=_object(
            {"exception": _any_object(), "invoice": _any_object()}, ("exception",)
        ),
        auth_scope="procurement.reconciliation.read",
        risk_class="read_only",
        operation="read",
        timeout_seconds=15.0,
    ),
    ToolContract(
        name="compare_invoice_contract",
        server=MCP_PROCUREMENT,
        description=(
            "Deterministically compare invoice lines against the contract terms in "
            "force on the invoice date and return variances. No LLM arithmetic."
        ),
        input_schema=_object(
            {
                "invoice_id": _UUID,
                "contract_id": _UUID,
                "include_header_rules": {"type": "boolean", "default": True},
            },
            ("invoice_id",),
        ),
        output_schema=_object(
            {
                "invoice_id": {"type": "string"},
                "contract_id": {"type": "string"},
                "contract_version_id": {"type": "string"},
                "lines": {"type": "array"},
                "totals": _any_object(),
                "findings": {"type": "array"},
            },
            ("invoice_id", "lines", "totals"),
        ),
        auth_scope="procurement.reconciliation.read",
        risk_class="read_only",
        operation="read",
        timeout_seconds=20.0,
    ),
    ToolContract(
        name="get_maverick_spend",
        server=MCP_PROCUREMENT,
        description=(
            "Return unmanaged SaaS detections with Jev probabilities, employee and "
            "department context, and approved-software overlap."
        ),
        input_schema=_object(
            {
                "status": {
                    "enum": ["open", "notified", "migrated", "dismissed", "all"],
                    "default": "open",
                },
                "days": {"type": "integer", "minimum": 1, "maximum": 365, "default": 90},
                "min_score": {"type": "number", "minimum": 0, "maximum": 1},
                "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 25},
                "offset": {"type": "integer", "minimum": 0, "default": 0},
            }
        ),
        output_schema=_object(
            {
                "detections": {"type": "array"},
                "count": {"type": "integer"},
                "total": {"type": "integer"},
            },
            ("detections",),
        ),
        auth_scope="procurement.maverick.read",
        risk_class="read_only",
        operation="read",
        timeout_seconds=20.0,
    ),
    ToolContract(
        name="get_spend_trend",
        server=MCP_PROCUREMENT,
        description=(
            "Return monthly or weekly spend series from invoices and card "
            "transactions with year-over-year comparison when data allows."
        ),
        input_schema=_object(
            {
                "start_date": _DATE,
                "end_date": _DATE,
                "granularity": {"enum": ["month", "week"], "default": "month"},
                "vendor_id": _UUID,
                "source": {
                    "enum": ["invoices", "card_transactions", "both"],
                    "default": "both",
                },
            }
        ),
        output_schema=_object(
            {
                "series": {"type": "array"},
                "total": {"type": "number"},
                "currency": {"type": "string"},
            },
            ("series", "total"),
        ),
        auth_scope="procurement.spend.read",
        risk_class="read_only",
        operation="read",
        timeout_seconds=20.0,
    ),
    ToolContract(
        name="calculate_spend",
        server=MCP_PROCUREMENT,
        description=(
            "Calculate authoritative spend for a required date range with optional "
            "vendor/category filters and vendor/month/category/department grouping."
        ),
        input_schema=_object(
            {
                "start_date": _DATE,
                "end_date": _DATE,
                "vendor_id": _UUID,
                "category": {"type": "string", "maxLength": 128},
                "source": {
                    "enum": ["invoices", "card_transactions", "both"],
                    "default": "both",
                },
                "group_by": {
                    "enum": ["vendor", "month", "category", "department"],
                    "default": "vendor",
                },
            },
            ("start_date", "end_date"),
        ),
        output_schema=_object(
            {
                "total": {"type": "number"},
                "currency": {"type": "string"},
                "group_by": {"type": "string"},
                "breakdown": {"type": "array"},
                "methodology": {"type": "string"},
            },
            ("total", "breakdown"),
        ),
        auth_scope="procurement.spend.read",
        risk_class="read_only",
        operation="read",
        timeout_seconds=25.0,
    ),
    ToolContract(
        name="calculate_savings",
        server=MCP_PROCUREMENT,
        description=(
            "Calculate verified and potential savings from the ledger plus open "
            "overbilling variance and shelfware opportunities."
        ),
        input_schema=_object(
            {
                "vendor_id": _UUID,
                "start_date": _DATE,
                "end_date": _DATE,
                "include_opportunities": {"type": "boolean", "default": True},
            }
        ),
        output_schema=_object(
            {
                "verified_hard_cash": {"type": "number"},
                "verified_avoidance": {"type": "number"},
                "potential_overbilling": {"type": "number"},
                "potential_shelfware": {"type": "number"},
                "currency": {"type": "string"},
                "components": {"type": "array"},
            },
            ("verified_hard_cash", "verified_avoidance"),
        ),
        auth_scope="procurement.savings.read",
        risk_class="read_only",
        operation="read",
        timeout_seconds=25.0,
    ),
)

_DOCUMENT_TOOLS: tuple[ToolContract, ...] = (
    ToolContract(
        name="search_documents",
        server=MCP_DOCUMENTS,
        description=(
            "Semantic search across indexed procurement documents. Returns source "
            "passages with vendor, document, page, section, and bbox provenance."
        ),
        input_schema=_object(
            {
                "query": {"type": "string", "minLength": 1, "maxLength": 2000},
                "vendor_id": _UUID,
                "document_type": {
                    "enum": [
                        "contract",
                        "amendment",
                        "invoice",
                        "purchase_order",
                        "policy",
                        "other",
                    ]
                },
                "limit": {"type": "integer", "minimum": 1, "maximum": 20, "default": 8},
            },
            ("query",),
        ),
        output_schema=_object(
            {"chunks": {"type": "array"}, "count": {"type": "integer"}},
            ("chunks",),
        ),
        auth_scope="documents.read",
        risk_class="read_only",
        operation="read",
        timeout_seconds=30.0,
        evidence_behavior="citations",
    ),
    ToolContract(
        name="search_contracts",
        server=MCP_DOCUMENTS,
        description=(
            "Search contracts and, by default, their amendments for clauses or "
            "commercial terms. Returns page-level source citations."
        ),
        input_schema=_object(
            {
                "query": {"type": "string", "minLength": 1, "maxLength": 2000},
                "vendor_id": _UUID,
                "include_amendments": {"type": "boolean", "default": True},
                "limit": {"type": "integer", "minimum": 1, "maximum": 20, "default": 8},
            },
            ("query",),
        ),
        output_schema=_object(
            {"chunks": {"type": "array"}, "count": {"type": "integer"}},
            ("chunks",),
        ),
        auth_scope="contracts.read",
        risk_class="read_only",
        operation="read",
        timeout_seconds=30.0,
        evidence_behavior="citations",
    ),
    ToolContract(
        name="search_invoices",
        server=MCP_DOCUMENTS,
        description="Search extracted invoice documents and return page-level source citations.",
        input_schema=_object(
            {
                "query": {"type": "string", "minLength": 1, "maxLength": 2000},
                "vendor_id": _UUID,
                "limit": {"type": "integer", "minimum": 1, "maximum": 20, "default": 8},
            },
            ("query",),
        ),
        output_schema=_object(
            {"chunks": {"type": "array"}, "count": {"type": "integer"}},
            ("chunks",),
        ),
        auth_scope="invoices.read",
        risk_class="read_only",
        operation="read",
        timeout_seconds=30.0,
        evidence_behavior="citations",
    ),
    ToolContract(
        name="search_vendor_policies",
        server=MCP_DOCUMENTS,
        description="Search vendor policies and other procurement documents for relevant passages.",
        input_schema=_object(
            {
                "query": {"type": "string", "minLength": 1, "maxLength": 2000},
                "vendor_id": _UUID,
                "limit": {"type": "integer", "minimum": 1, "maximum": 20, "default": 8},
            },
            ("query",),
        ),
        output_schema=_object(
            {"chunks": {"type": "array"}, "count": {"type": "integer"}},
            ("chunks",),
        ),
        auth_scope="policies.read",
        risk_class="read_only",
        operation="read",
        timeout_seconds=30.0,
        evidence_behavior="citations",
    ),
    ToolContract(
        name="search_document_chunks",
        server=MCP_DOCUMENTS,
        description=(
            "Search indexed passages with optional document and vendor filters. "
            "Use get_source_provenance to expand a chunk."
        ),
        input_schema=_object(
            {
                "query": {"type": "string", "minLength": 1, "maxLength": 2000},
                "vendor_id": _UUID,
                "document_id": _UUID,
                "document_type": {"type": "string", "maxLength": 32},
                "limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 10},
                "offset": {"type": "integer", "minimum": 0, "default": 0},
            },
            ("query",),
        ),
        output_schema=_object(
            {"chunks": {"type": "array"}, "count": {"type": "integer"}},
            ("chunks",),
        ),
        auth_scope="documents.read",
        risk_class="read_only",
        operation="read",
        timeout_seconds=30.0,
        evidence_behavior="citations",
    ),
    ToolContract(
        name="get_document",
        server=MCP_DOCUMENTS,
        description=(
            "Return document metadata, extraction status, page count, and provenance "
            "summaries. Never returns raw bucket contents or model summaries as source."
        ),
        input_schema=_object(
            {
                "document_id": _UUID,
                "include_provenance": {"type": "boolean", "default": True},
            },
            ("document_id",),
        ),
        output_schema=_object(
            {"document": _any_object(), "provenance": {"type": "array"}},
            ("document",),
        ),
        auth_scope="documents.read",
        risk_class="read_only",
        operation="read",
        timeout_seconds=20.0,
        evidence_behavior="citations",
    ),
    ToolContract(
        name="get_document_page",
        server=MCP_DOCUMENTS,
        description=(
            "Return the extracted text blocks, tables, and bounding boxes for one "
            "page of a source document."
        ),
        input_schema=_object(
            {"document_id": _UUID, "page": {"type": "integer", "minimum": 1}},
            ("document_id", "page"),
        ),
        output_schema=_object(
            {
                "document_id": {"type": "string"},
                "page": {"type": "integer"},
                "text": {"type": "string"},
                "text_blocks": {"type": "array"},
                "tables": {"type": "array"},
                "content_type": {"type": "string"},
            },
            ("document_id", "page"),
        ),
        auth_scope="documents.read",
        risk_class="read_only",
        operation="read",
        timeout_seconds=25.0,
        evidence_behavior="citations",
    ),
    ToolContract(
        name="get_document_section",
        server=MCP_DOCUMENTS,
        description="Return indexed passages for a named section of one document.",
        input_schema=_object(
            {
                "document_id": _UUID,
                "section": {"type": "string", "minLength": 1, "maxLength": 200},
                "limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 20},
            },
            ("document_id", "section"),
        ),
        output_schema=_object(
            {"document_id": {"type": "string"}, "chunks": {"type": "array"}},
            ("document_id", "chunks"),
        ),
        auth_scope="documents.read",
        risk_class="read_only",
        operation="read",
        timeout_seconds=25.0,
        evidence_behavior="citations",
    ),
    ToolContract(
        name="get_document_chunks",
        server=MCP_DOCUMENTS,
        description="List indexed passages for one document with stable offsets.",
        input_schema=_object(
            {
                "document_id": _UUID,
                "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 25},
                "offset": {"type": "integer", "minimum": 0, "default": 0},
            },
            ("document_id",),
        ),
        output_schema=_object(
            {"document_id": {"type": "string"}, "chunks": {"type": "array"}},
            ("document_id", "chunks"),
        ),
        auth_scope="documents.read",
        risk_class="read_only",
        operation="read",
        timeout_seconds=25.0,
        evidence_behavior="citations",
    ),
    ToolContract(
        name="get_source_provenance",
        server=MCP_DOCUMENTS,
        description=(
            "Return the source document, page, section, bbox, and raw passage for "
            "one chunk id."
        ),
        input_schema=_object({"chunk_id": _UUID}, ("chunk_id",)),
        output_schema=_object(
            {
                "chunk_id": {"type": "string"},
                "document_id": {"type": "string"},
                "page": {"type": ["integer", "null"]},
                "section": {"type": ["string", "null"]},
                "bbox": {"type": ["array", "null"]},
                "content_type": {"type": "string"},
            },
            ("chunk_id", "document_id"),
        ),
        auth_scope="documents.read",
        risk_class="read_only",
        operation="read",
        timeout_seconds=20.0,
        evidence_behavior="citations",
    ),
)

_EXTERNAL_TOOLS: tuple[ToolContract, ...] = (
    ToolContract(
        name="lookup_external_vendor",
        server=MCP_EXTERNAL,
        description=(
            "Look up a vendor in the configured ERP/finance system and the local "
            "vendor master. Reports integration availability explicitly."
        ),
        input_schema=_object(
            {
                "name": {"type": "string", "maxLength": 256},
                "domain": {"type": "string", "maxLength": 256},
                "external_id": {"type": "string", "maxLength": 128},
            }
        ),
        output_schema=_object(
            {
                "available": {"type": "boolean"},
                "external": {"type": "array"},
                "local": _nullable_object(),
                "reason": _nullable_string(),
            },
            ("available",),
        ),
        auth_scope="procurement.vendor.read",
        risk_class="read_only",
        operation="read",
        timeout_seconds=20.0,
        evidence_behavior="records",
    ),
    ToolContract(
        name="search_external_system",
        server=MCP_EXTERNAL,
        description=(
            "Search a configured external system (ERP or collaboration) with a "
            "bounded query. Never exposes credentials or unrestricted browsing."
        ),
        input_schema=_object(
            {
                "system": {"enum": ["erp", "slack"], "default": "erp"},
                "query": {"type": "string", "minLength": 1, "maxLength": 500},
                "limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 10},
            },
            ("query",),
        ),
        output_schema=_object(
            {
                "available": {"type": "boolean"},
                "results": {"type": "array"},
                "reason": _nullable_string(),
            },
            ("available", "results"),
        ),
        auth_scope="external.erp.write",
        risk_class="read_only",
        operation="read",
        timeout_seconds=20.0,
    ),
    ToolContract(
        name="create_procurement_task",
        server=MCP_EXTERNAL,
        description=(
            "Create a tracked procurement task. Supports dry-run preview and "
            "idempotency keys."
        ),
        input_schema=_object(
            {
                "title": {"type": "string", "minLength": 1, "maxLength": 256},
                "description": {"type": "string", "maxLength": 8000},
                "vendor_id": _UUID,
                "priority": {"enum": ["low", "medium", "high"], "default": "medium"},
                "due_at": {"type": "string", "format": "date-time"},
                "idempotency_key": _IDEMPOTENCY,
                "dry_run": _DRY_RUN,
            },
            ("title", "idempotency_key"),
        ),
        output_schema=_object(
            {"workflow_id": {"type": "string"}, "status": {"type": "string"}},
            ("status",),
        ),
        auth_scope="procurement.task.write",
        risk_class="low_risk",
        operation="write",
        timeout_seconds=20.0,
        idempotent=True,
        evidence_behavior="records",
        audit_event_type="mcp.tool.write",
    ),
    ToolContract(
        name="create_review_task",
        server=MCP_EXTERNAL,
        description=(
            "Create a human review task for an invoice, contract, or extraction. "
            "Supports dry-run preview and idempotency keys."
        ),
        input_schema=_object(
            {
                "title": {"type": "string", "minLength": 1, "maxLength": 256},
                "description": {"type": "string", "maxLength": 8000},
                "reference_type": {
                    "enum": ["invoice", "contract", "purchase_order", "document", "exception"],
                },
                "reference_id": _UUID,
                "assignee_user_id": _UUID,
                "due_at": {"type": "string", "format": "date-time"},
                "idempotency_key": _IDEMPOTENCY,
                "dry_run": _DRY_RUN,
            },
            ("title", "reference_type", "reference_id", "idempotency_key"),
        ),
        output_schema=_object(
            {"workflow_id": {"type": "string"}, "status": {"type": "string"}},
            ("status",),
        ),
        auth_scope="procurement.task.write",
        risk_class="low_risk",
        operation="write",
        timeout_seconds=20.0,
        idempotent=True,
        evidence_behavior="records",
        audit_event_type="mcp.tool.write",
    ),
    ToolContract(
        name="create_renewal_reminder",
        server=MCP_EXTERNAL,
        description=(
            "Create a notice-deadline reminder workflow for a contract. Supports "
            "dry-run preview and idempotency keys."
        ),
        input_schema=_object(
            {
                "contract_id": _UUID,
                "vendor_id": _UUID,
                "remind_before_days": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 180,
                    "default": 15,
                },
                "notes": {"type": "string", "maxLength": 4000},
                "idempotency_key": _IDEMPOTENCY,
                "dry_run": _DRY_RUN,
            },
            ("contract_id", "idempotency_key"),
        ),
        output_schema=_object(
            {"workflow_id": {"type": "string"}, "status": {"type": "string"}},
            ("status",),
        ),
        auth_scope="procurement.renewal.write",
        risk_class="low_risk",
        operation="write",
        timeout_seconds=20.0,
        idempotent=True,
        evidence_behavior="records",
        audit_event_type="mcp.tool.write",
    ),
    ToolContract(
        name="prepare_renewal_brief",
        server=MCP_EXTERNAL,
        description=(
            "Create a renewal-preparation workflow that carries the contract, "
            "vendor, and requested brief options for the negotiation workspace."
        ),
        input_schema=_object(
            {
                "contract_id": _UUID,
                "vendor_id": _UUID,
                "requested_sections": {
                    "type": "array",
                    "items": {
                        "enum": [
                            "commercial_position",
                            "timeline",
                            "utilization",
                            "savings",
                            "leverage",
                            "questions",
                        ]
                    },
                    "default": ["commercial_position", "timeline", "utilization", "leverage"],
                },
                "notes": {"type": "string", "maxLength": 4000},
                "idempotency_key": _IDEMPOTENCY,
                "dry_run": _DRY_RUN,
            },
            ("contract_id", "idempotency_key"),
        ),
        output_schema=_object(
            {"workflow_id": {"type": "string"}, "status": {"type": "string"}},
            ("status",),
        ),
        auth_scope="procurement.renewal.write",
        risk_class="low_risk",
        operation="write",
        timeout_seconds=20.0,
        idempotent=True,
        evidence_behavior="records",
        audit_event_type="mcp.tool.write",
    ),
    ToolContract(
        name="start_human_review_workflow",
        server=MCP_EXTERNAL,
        description=(
            "Start a human review workflow for a low-confidence extraction or "
            "commercial decision. Supports dry-run preview and idempotency keys."
        ),
        input_schema=_object(
            {
                "workflow_type": {
                    "enum": [
                        "human_review",
                        "invoice_approval",
                        "contract_review",
                        "purchase_order_approval",
                        "vendor_onboarding",
                    ]
                },
                "reference_type": {"type": "string", "minLength": 1, "maxLength": 32},
                "reference_id": _UUID,
                "reason": {"type": "string", "maxLength": 4000},
                "assignee_user_id": _UUID,
                "idempotency_key": _IDEMPOTENCY,
                "dry_run": _DRY_RUN,
            },
            ("workflow_type", "reference_type", "reference_id", "idempotency_key"),
        ),
        output_schema=_object(
            {"workflow_id": {"type": "string"}, "status": {"type": "string"}},
            ("status",),
        ),
        auth_scope="procurement.workflow.write",
        risk_class="low_risk",
        operation="write",
        timeout_seconds=20.0,
        idempotent=True,
        evidence_behavior="records",
        audit_event_type="mcp.tool.write",
    ),
    ToolContract(
        name="send_slack_message",
        server=MCP_EXTERNAL,
        description=(
            "Send an internal Slack notification. Supports dry-run preview and "
            "idempotency keys; never writes to external vendors."
        ),
        input_schema=_object(
            {
                "channel": {"type": "string", "minLength": 1, "maxLength": 128},
                "text": {"type": "string", "minLength": 1, "maxLength": 4000},
                "idempotency_key": _IDEMPOTENCY,
                "dry_run": _DRY_RUN,
            },
            ("channel", "text", "idempotency_key"),
        ),
        output_schema=_object(
            {"delivered": {"type": "boolean"}, "status": {"type": "string"}},
            ("status",),
        ),
        auth_scope="external.slack.write",
        risk_class="low_risk",
        operation="write",
        timeout_seconds=20.0,
        idempotent=True,
        evidence_behavior="records",
        audit_event_type="mcp.tool.write",
    ),
    ToolContract(
        name="send_email",
        server=MCP_EXTERNAL,
        description=(
            "Send an email through the configured mail transport. High risk: "
            "requires a human confirmation token for execution. Dry-run is allowed."
        ),
        input_schema=_object(
            {
                "to": {
                    "type": "array",
                    "items": {"type": "string", "format": "email"},
                    "minItems": 1,
                    "maxItems": 20,
                },
                "subject": {"type": "string", "minLength": 1, "maxLength": 256},
                "body": {"type": "string", "minLength": 1, "maxLength": 20000},
                "cc": {"type": "array", "items": {"type": "string", "format": "email"}},
                "idempotency_key": _IDEMPOTENCY,
                "confirmation_token": _CONFIRM_TOKEN,
                "dry_run": _DRY_RUN,
            },
            ("to", "subject", "body", "idempotency_key"),
        ),
        output_schema=_object(
            {"delivered": {"type": "boolean"}, "status": {"type": "string"}},
            ("status",),
        ),
        auth_scope="external.email.write",
        risk_class="high_risk",
        operation="write",
        timeout_seconds=30.0,
        idempotent=True,
        evidence_behavior="records",
        audit_event_type="mcp.tool.high_risk",
    ),
    ToolContract(
        name="submit_procurement_workflow",
        server=MCP_EXTERNAL,
        description=(
            "Submit a consequential procurement workflow (approve invoice, cancel "
            "contract, modify terms/PO, or commit spend). High risk: requires a "
            "human confirmation token. Dry-run is allowed."
        ),
        input_schema=_object(
            {
                "action": {
                    "enum": [
                        "approve_invoice",
                        "cancel_contract",
                        "modify_contract_terms",
                        "change_purchase_order",
                        "send_external_vendor_communication",
                        "commit_financial_spend",
                    ]
                },
                "reference_type": {
                    "enum": ["invoice", "contract", "purchase_order", "vendor"],
                },
                "reference_id": _UUID,
                "parameters": {"type": "object", "additionalProperties": True},
                "idempotency_key": _IDEMPOTENCY,
                "confirmation_token": _CONFIRM_TOKEN,
                "dry_run": _DRY_RUN,
            },
            ("action", "reference_type", "reference_id", "idempotency_key"),
        ),
        output_schema=_object(
            {"workflow_id": {"type": "string"}, "status": {"type": "string"}},
            ("status",),
        ),
        auth_scope="external.erp.write",
        risk_class="high_risk",
        operation="write",
        timeout_seconds=30.0,
        idempotent=True,
        evidence_behavior="records",
        audit_event_type="mcp.tool.high_risk",
    ),
)

TOOL_CONTRACTS: dict[str, ToolContract] = {
    contract.name: contract
    for contract in (*_PROCUREMENT_TOOLS, *_DOCUMENT_TOOLS, *_EXTERNAL_TOOLS)
}


def contracts_for_server(server: str) -> tuple[ToolContract, ...]:
    """Return every contract declared for one logical MCP server."""
    return tuple(
        contract for contract in TOOL_CONTRACTS.values() if contract.server == server
    )


def contract_for_tool(tool_name: str) -> ToolContract | None:
    """Return the declared contract for a tool name, or None when unknown."""
    return TOOL_CONTRACTS.get(tool_name)


def role_allows(role: str, scope: str) -> bool:
    """Return True when a role grants an authorization scope."""
    return scope in SCOPES_BY_ROLE.get(role, frozenset())


def tool_names_for_server(server: str) -> tuple[str, ...]:
    """Return declared tool names for a server in declaration order."""
    return tuple(contract.name for contract in contracts_for_server(server))
