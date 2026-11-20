"""Comprehensive tests for canonical MCP tool contracts (PRD 25.7)."""


from zellovest_shared.mcp_contracts import (
    MCP_DOCUMENTS,
    MCP_EXTERNAL,
    MCP_PROCUREMENT,
    MCP_SERVERS,
    PROCUREMENT_ROLE,
    TOOL_CONTRACTS,
    contract_for_tool,
    contracts_for_server,
    role_allows,
)


def test_mcp_servers_and_counts():
    """Exactly three logical MCP servers with 33 tools total (PRD 25.1 / 25.12)."""
    assert len(MCP_SERVERS) == 3
    assert set(MCP_SERVERS) == {MCP_PROCUREMENT, MCP_DOCUMENTS, MCP_EXTERNAL}

    proc_tools = contracts_for_server(MCP_PROCUREMENT)
    doc_tools = contracts_for_server(MCP_DOCUMENTS)
    ext_tools = contracts_for_server(MCP_EXTERNAL)

    # MCP-1 has 13 tools
    assert len(proc_tools) == 13
    # MCP-2 has 10 tools
    assert len(doc_tools) == 10
    # MCP-3 has 10 tools
    assert len(ext_tools) == 10
    assert len(TOOL_CONTRACTS) == 33


def test_mcp1_procurement_tool_names():
    """Verify all 13 MCP-1 Procurement Intelligence tools exist."""
    expected = {
        "get_vendor",
        "get_contract",
        "get_invoice",
        "get_purchase_order",
        "get_vendor_spend",
        "get_license_usage",
        "find_renewals",
        "get_reconciliation_exception",
        "compare_invoice_contract",
        "get_maverick_spend",
        "get_spend_trend",
        "calculate_spend",
        "calculate_savings",
    }
    actual = {t.name for t in contracts_for_server(MCP_PROCUREMENT)}
    assert actual == expected

    for tool in contracts_for_server(MCP_PROCUREMENT):
        assert tool.server == MCP_PROCUREMENT
        assert tool.operation == "read"
        assert tool.risk_class == "read_only"
        assert tool.read_only is True
        assert tool.requires_confirmation is False
        assert tool.tenant_scoped is True


def test_mcp2_document_knowledge_tool_names():
    """Verify all 10 MCP-2 Document Knowledge tools exist."""
    expected = {
        "search_documents",
        "search_contracts",
        "search_invoices",
        "search_vendor_policies",
        "search_document_chunks",
        "get_document",
        "get_document_page",
        "get_document_section",
        "get_document_chunks",
        "get_source_provenance",
    }
    actual = {t.name for t in contracts_for_server(MCP_DOCUMENTS)}
    assert actual == expected

    for tool in contracts_for_server(MCP_DOCUMENTS):
        assert tool.server == MCP_DOCUMENTS
        assert tool.operation == "read"
        assert tool.risk_class == "read_only"
        assert tool.read_only is True
        assert tool.requires_confirmation is False
        assert tool.tenant_scoped is True


def test_mcp3_external_systems_tool_names_and_risk_classes():
    """Verify all 10 MCP-3 tools and their risk classifications (PRD 25.4)."""
    expected = {
        "lookup_external_vendor",
        "search_external_system",
        "create_procurement_task",
        "create_review_task",
        "create_renewal_reminder",
        "prepare_renewal_brief",
        "start_human_review_workflow",
        "send_slack_message",
        "send_email",
        "submit_procurement_workflow",
    }
    actual = {t.name for t in contracts_for_server(MCP_EXTERNAL)}
    assert actual == expected

    read_only = {"lookup_external_vendor", "search_external_system"}
    low_risk = {
        "create_procurement_task",
        "create_review_task",
        "create_renewal_reminder",
        "prepare_renewal_brief",
        "start_human_review_workflow",
        "send_slack_message",
    }
    high_risk = {"send_email", "submit_procurement_workflow"}

    for name in read_only:
        c = TOOL_CONTRACTS[name]
        assert c.risk_class == "read_only"
        assert c.operation == "read"
        assert c.requires_confirmation is False

    for name in low_risk:
        c = TOOL_CONTRACTS[name]
        assert c.risk_class == "low_risk"
        assert c.operation == "write"
        assert c.requires_confirmation is False
        assert c.read_only is False

    for name in high_risk:
        c = TOOL_CONTRACTS[name]
        assert c.risk_class == "high_risk"
        assert c.operation == "write"
        assert c.requires_confirmation is True
        assert c.read_only is False


def test_strict_input_schema_rejects_extra_properties():
    """Strict input schema must enforce additionalProperties=False (PRD 25.7)."""
    for contract in TOOL_CONTRACTS.values():
        strict = contract.strict_input_schema()
        assert strict["additionalProperties"] is False
        assert strict["type"] == "object"
        assert "properties" in strict


def test_role_authorization():
    """Role mapping grants access to procurement_member and denies unknown roles."""
    assert role_allows(PROCUREMENT_ROLE, "procurement.vendor.read") is True
    assert role_allows(PROCUREMENT_ROLE, "documents.read") is True
    assert role_allows(PROCUREMENT_ROLE, "external.slack.write") is True
    assert role_allows(PROCUREMENT_ROLE, "nonexistent.scope") is False
    assert role_allows("unauthorized_role", "procurement.vendor.read") is False


def test_contract_for_tool():
    """contract_for_tool identifies the contract and owning server."""
    c1 = contract_for_tool("get_vendor")
    assert c1 is not None
    assert c1.server == MCP_PROCUREMENT

    c2 = contract_for_tool("search_documents")
    assert c2 is not None
    assert c2.server == MCP_DOCUMENTS

    c3 = contract_for_tool("send_slack_message")
    assert c3 is not None
    assert c3.server == MCP_EXTERNAL

    assert contract_for_tool("nonexistent_tool") is None


def test_contract_metadata_serialization():
    """as_metadata contains all fields required for discovery."""
    contract = TOOL_CONTRACTS["get_vendor"]
    meta = contract.as_metadata()
    assert meta["name"] == "get_vendor"
    assert meta["server"] == MCP_PROCUREMENT
    assert meta["risk_class"] == "read_only"
    assert meta["operation"] == "read"
    assert meta["timeout_seconds"] == 10.0
    assert meta["idempotent"] is True
    assert meta["requires_confirmation"] is False
    assert "auth_scope" in meta
    assert "version" in meta
