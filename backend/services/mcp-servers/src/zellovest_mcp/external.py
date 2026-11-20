"""MCP-3 External Systems and Actions server.

The server separates three risk classes:

* ``read_only`` - external lookups that never mutate anything.
* ``low_risk`` - tracked internal workflows (tasks, reviews, reminders,
  Slack notifications) that are reversible and idempotent.
* ``high_risk`` - consequential actions (email to counterparties, invoice
  approval, contract cancellation, term/PO changes, spend commitments) that
  require an HMAC confirmation token minted only after explicit human
  confirmation.

Every write accepts an idempotency key and a ``dry_run`` flag. A repeated key
with identical parameters returns the original record instead of creating a
duplicate; a repeated key with different parameters is a conflict.

External integrations are optional. When an integration is not configured, the
tool reports ``available: false`` with a reason instead of pretending success
(PRD 25.8).
"""

from __future__ import annotations

import asyncio
import smtplib
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from email.message import EmailMessage
from typing import Any

import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from zellovest_shared.db.core import Vendor
from zellovest_shared.db.intelligence import (
    Workflow,
    WorkflowStatus,
    WorkflowType,
)
from zellovest_shared.db.session import async_session_context
from zellovest_shared.db.transact import (
    Contract,
    ContractTermsVersion,
    Invoice,
    PurchaseOrder,
)
from zellovest_shared.logging_conf import get_logger
from zellovest_shared.mcp_confirmation import (
    ConfirmationError,
    parameters_digest,
    verify_confirmation_token,
)
from zellovest_shared.mcp_contracts import MCP_EXTERNAL

from zellovest_mcp.errors import ErrorCode, ToolError, invalid, not_found
from zellovest_mcp.runtime import McpServerRuntime
from zellovest_mcp.settings import get_mcp_settings

logger = get_logger(__name__)

SERVER_NAME = MCP_EXTERNAL
SERVER_VERSION = "1.0.0"

external = McpServerRuntime(
    server_name=SERVER_NAME,
    display_name="Zellovest External Systems MCP",
    version=SERVER_VERSION,
)

_ACTION_WORKFLOW: dict[str, WorkflowType] = {
    "approve_invoice": WorkflowType.INVOICE_APPROVAL,
    "cancel_contract": WorkflowType.CONTRACT_REVIEW,
    "modify_contract_terms": WorkflowType.CONTRACT_REVIEW,
    "change_purchase_order": WorkflowType.PURCHASE_ORDER_APPROVAL,
    "send_external_vendor_communication": WorkflowType.VENDOR_ONBOARDING,
    "commit_financial_spend": WorkflowType.INVOICE_APPROVAL,
}


def _confirmation_secret() -> str:
    """Return the shared confirmation secret (service token as fallback)."""
    settings = get_mcp_settings()
    return settings.confirmation_secret or settings.service_token


def _require_confirmation(
    context,
    tool_name: str,
    arguments: dict[str, Any],
) -> None:
    """Verify the human confirmation token for a high-risk action.

    Args:
        context: Authenticated request context.
        tool_name: High-risk tool being executed.
        arguments: Tool arguments including token and idempotency key.

    Raises:
        ToolError: ``confirmation_required`` when the token is missing or does
            not bind to this tenant, tool, idempotency key, and parameters.
    """
    try:
        verify_confirmation_token(
            secret=_confirmation_secret(),
            token=str(arguments.get("confirmation_token") or ""),
            tenant_id=context.tenant_id,
            tool_name=tool_name,
            idempotency_key=str(arguments.get("idempotency_key") or ""),
            parameters=arguments,
        )
    except ConfirmationError as exc:
        raise ToolError(
            ErrorCode.CONFIRMATION_REQUIRED,
            str(exc),
            details={"tool": tool_name, "risk_class": "high_risk"},
        ) from exc


def _uuid_arg(value: str, label: str) -> uuid.UUID:
    """Parse a UUID argument or raise a typed validation error."""
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError, AttributeError) as exc:
        raise invalid(f"{label} must be a UUID") from exc


def _parse_due(value: str | None) -> datetime | None:
    """Parse an optional ISO date-time into an aware UTC datetime."""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise invalid("due_at must be an ISO-8601 date-time") from exc
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _workflow_json(
    workflow: Workflow, *, replay: bool = False, dry_run: bool = False
) -> dict[str, Any]:
    """Serialize a workflow record for a write tool response."""
    return {
        "workflow_id": str(workflow.id),
        "status": workflow.status.value,
        "workflow_type": workflow.workflow_type.value,
        "title": workflow.title,
        "due_at": workflow.due_at.isoformat() if workflow.due_at else None,
        "idempotent_replay": replay,
        "dry_run": dry_run,
        "as_of": datetime.now(UTC).isoformat(),
        "summary": f"{workflow.workflow_type.value} {workflow.status.value}: {workflow.title}",
    }


async def _find_idempotent(
    session: AsyncSession, tenant_id: str, idempotency_key: str
) -> Workflow | None:
    """Return a workflow previously created with the same idempotency key."""
    return await session.scalar(
        select(Workflow).where(
            Workflow.tenant_id == tenant_id,
            Workflow.extra["idempotency_key"].as_string() == idempotency_key,
        )
    )


async def _create_workflow(
    *,
    context,
    tool_name: str,
    idempotency_key: str,
    workflow_type: WorkflowType,
    title: str,
    description: str | None,
    reference_type: str | None,
    reference_id: uuid.UUID | None,
    arguments: dict[str, Any],
    due_at: datetime | None = None,
    assignee_user_id: uuid.UUID | None = None,
    total_steps: int = 3,
    dry_run: bool = False,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create one idempotent workflow or return a dry-run preview.

    Args:
        context: Authenticated request context.
        tool_name: Originating tool (stored for audit lineage).
        idempotency_key: Client key that makes retries safe.
        workflow_type: Workflow category to persist.
        title: Human-readable title.
        description: Optional details.
        reference_type: Optional domain object type.
        reference_id: Optional domain object id.
        arguments: Full arguments for the parameter digest.
        due_at: Optional due date.
        assignee_user_id: Optional assignee.
        total_steps: Workflow step count.
        dry_run: When True, nothing is persisted.
        extra: Additional metadata merged into the workflow.

    Returns:
        Serialized workflow, or a dry-run preview with ``status="dry_run"``.

    Raises:
        ToolError: ``conflict`` when the key was reused with different inputs.
    """
    digest = parameters_digest(arguments)
    async with async_session_context() as session:
        existing = await _find_idempotent(session, context.tenant_id, idempotency_key)
        if existing is not None:
            stored_digest = (existing.extra or {}).get("parameters_digest")
            if stored_digest and stored_digest != digest:
                raise ToolError(
                    ErrorCode.CONFLICT,
                    "idempotency_key was already used with different parameters",
                    details={"workflow_id": str(existing.id)},
                )
            return _workflow_json(existing, replay=True)

        if dry_run:
            return {
                "workflow_id": str(uuid.uuid4()),
                "status": "dry_run",
                "workflow_type": workflow_type.value,
                "title": title,
                "due_at": due_at.isoformat() if due_at else None,
                "preview": {
                    "description": description,
                    "reference_type": reference_type,
                    "reference_id": str(reference_id) if reference_id else None,
                    "assignee_user_id": str(assignee_user_id) if assignee_user_id else None,
                },
                "idempotent_replay": False,
                "dry_run": True,
                "as_of": datetime.now(UTC).isoformat(),
                "summary": f"dry run: would create {workflow_type.value} {title!r}",
            }

        metadata = {
            "idempotency_key": idempotency_key,
            "parameters_digest": digest,
            "created_by_tool": tool_name,
            **(extra or {}),
        }
        workflow = Workflow(
            tenant_id=context.tenant_id,
            workflow_type=workflow_type,
            title=title[:256],
            description=description,
            reference_type=reference_type,
            reference_id=reference_id,
            assignee_user_id=assignee_user_id,
            status=WorkflowStatus.PENDING,
            current_step=1,
            total_steps=total_steps,
            due_at=due_at,
            extra=metadata,
        )
        session.add(workflow)
        await session.commit()
        await session.refresh(workflow)
        return _workflow_json(workflow)


# ---------------------------------------------------------------------------
# Read-only tools
# ---------------------------------------------------------------------------


async def _erp_get(path: str, params: dict[str, Any]) -> tuple[bool, Any, str | None]:
    """Call the configured ERP read API.

    Returns:
        Tuple of ``(available, payload, reason)``. ``available`` is False when
        the integration is not configured or the call failed.
    """
    settings = get_mcp_settings()
    if not settings.erp_base_url or not settings.erp_api_token:
        return False, None, "erp_not_configured"
    headers = {"Authorization": f"Bearer {settings.erp_api_token}"}
    try:
        async with httpx.AsyncClient(timeout=settings.erp_timeout_seconds) as client:
            response = await client.get(
                f"{settings.erp_base_url.rstrip('/')}{path}", params=params, headers=headers
            )
            response.raise_for_status()
            return True, response.json(), None
    except Exception as exc:
        logger.warning("erp_lookup_failed", path=path, error_class=type(exc).__name__)
        return False, None, "erp_unavailable"


@external.tool("lookup_external_vendor")
async def lookup_external_vendor(context, arguments: dict[str, Any]) -> dict[str, Any]:
    """Look up a vendor in the ERP and the local vendor master."""
    name = arguments.get("name")
    domain = arguments.get("domain")
    external_id = arguments.get("external_id")
    if not any((name, domain, external_id)):
        raise invalid("one of name, domain, or external_id is required")

    async with async_session_context() as session:
        local_stmt = select(Vendor).where(Vendor.tenant_id == context.tenant_id)
        if external_id:
            local_stmt = local_stmt.where(Vendor.external_vendor_id == external_id)
        elif domain:
            local_stmt = local_stmt.where(
                func.lower(Vendor.domain) == domain.lower().removeprefix("www.")
            )
        else:
            local_stmt = local_stmt.where(Vendor.name.ilike(f"%{name}%"))
        local_vendor = await session.scalar(local_stmt.limit(1))

    params: dict[str, Any] = {}
    if external_id:
        params["id"] = external_id
    if name:
        params["name"] = name
    if domain:
        params["domain"] = domain
    available, payload, reason = await _erp_get("/vendors", params)
    records = payload if isinstance(payload, list) else (payload or {}).get("items") or []
    return {
        "available": available,
        "external": (
            [
                {
                    "id": item.get("id"),
                    "name": item.get("name"),
                    "domain": item.get("domain"),
                    "status": item.get("status"),
                }
                for item in records[:10]
            ]
            if available
            else []
        ),
        "local": (
            {
                "id": str(local_vendor.id),
                "name": local_vendor.name,
                "domain": local_vendor.domain,
                "external_vendor_id": local_vendor.external_vendor_id,
                "status": local_vendor.status,
            }
            if local_vendor
            else None
        ),
        "reason": reason,
        "as_of": datetime.now(UTC).isoformat(),
        "summary": (
            f"ERP available with {len(records[:10])} matches"
            if available
            else (
                f"ERP unavailable ({reason}); local vendor "
                f"{'found' if local_vendor else 'not found'}"
            )
        ),
    }


@external.tool("search_external_system")
async def search_external_system(context, arguments: dict[str, Any]) -> dict[str, Any]:
    """Run a bounded search against the ERP or an internal Slack workspace."""
    settings = get_mcp_settings()
    system = arguments.get("system") or "erp"
    query = arguments["query"]
    limit = int(arguments.get("limit") or 10)

    if system == "erp":
        available, payload, reason = await _erp_get(
            "/search", {"q": query, "limit": limit}
        )
        records = payload if isinstance(payload, list) else (payload or {}).get("items") or []
        results = [
            {
                "id": item.get("id"),
                "title": item.get("name") or item.get("title"),
                "type": item.get("type"),
                "snippet": str(item.get("description") or "")[:500],
            }
            for item in records[:limit]
        ]
        return {
            "available": available,
            "results": results if available else [],
            "reason": reason,
            "as_of": datetime.now(UTC).isoformat(),
            "summary": (
                f"{len(results)} ERP results"
                if available
                else f"ERP unavailable ({reason})"
            ),
        }

    if not settings.slack_search_token:
        return {
            "available": False,
            "results": [],
            "reason": "slack_not_configured",
            "as_of": datetime.now(UTC).isoformat(),
            "summary": "Slack search is not configured",
        }
    try:
        async with httpx.AsyncClient(timeout=settings.slack_timeout_seconds) as client:
            response = await client.get(
                "https://slack.com/api/search.messages",
                params={"query": query, "count": limit},
                headers={"Authorization": f"Bearer {settings.slack_search_token}"},
            )
            response.raise_for_status()
            payload = response.json()
        if not payload.get("ok"):
            raise ToolError(
                ErrorCode.INTEGRATION_UNAVAILABLE,
                f"Slack search failed: {payload.get('error', 'unknown_error')}",
            )
        matches = ((payload.get("messages") or {}).get("matches") or [])[:limit]
        return {
            "available": True,
            "results": [
                {
                    "channel": (match.get("channel") or {}).get("name"),
                    "timestamp": match.get("ts"),
                    "author": (match.get("username") or match.get("user")),
                    "text": str(match.get("text") or "")[:500],
                    "permalink": match.get("permalink"),
                }
                for match in matches
            ],
            "reason": None,
            "as_of": datetime.now(UTC).isoformat(),
            "summary": f"{len(matches)} Slack messages matched",
        }
    except ToolError:
        raise
    except Exception as exc:
        logger.warning("slack_search_failed", error_class=type(exc).__name__)
        return {
            "available": False,
            "results": [],
            "reason": "slack_unavailable",
            "as_of": datetime.now(UTC).isoformat(),
            "summary": "Slack search is temporarily unavailable",
        }


# ---------------------------------------------------------------------------
# Low-risk write tools
# ---------------------------------------------------------------------------


@external.tool("create_procurement_task")
async def create_procurement_task(context, arguments: dict[str, Any]) -> dict[str, Any]:
    """Create an idempotent, optionally dry-run, procurement task."""
    vendor_id = (
        _uuid_arg(arguments["vendor_id"], "vendor_id")
        if arguments.get("vendor_id")
        else None
    )
    return await _create_workflow(
        context=context,
        tool_name="create_procurement_task",
        idempotency_key=arguments["idempotency_key"],
        workflow_type=WorkflowType.HUMAN_REVIEW,
        title=arguments["title"],
        description=arguments.get("description"),
        reference_type="vendor" if vendor_id else None,
        reference_id=vendor_id,
        arguments=arguments,
        due_at=_parse_due(arguments.get("due_at")),
        dry_run=bool(arguments.get("dry_run", True)),
        extra={
            "priority": arguments.get("priority") or "medium",
            "kind": "procurement_task",
        },
    )


@external.tool("create_review_task")
async def create_review_task(context, arguments: dict[str, Any]) -> dict[str, Any]:
    """Create an idempotent human review task for a domain object."""
    assignee = (
        _uuid_arg(arguments["assignee_user_id"], "assignee_user_id")
        if arguments.get("assignee_user_id")
        else None
    )
    return await _create_workflow(
        context=context,
        tool_name="create_review_task",
        idempotency_key=arguments["idempotency_key"],
        workflow_type=WorkflowType.HUMAN_REVIEW,
        title=arguments["title"],
        description=arguments.get("description"),
        reference_type=arguments["reference_type"],
        reference_id=_uuid_arg(arguments["reference_id"], "reference_id"),
        arguments=arguments,
        due_at=_parse_due(arguments.get("due_at")),
        assignee_user_id=assignee,
        dry_run=bool(arguments.get("dry_run", True)),
        extra={"kind": "review_task"},
    )


@external.tool("create_renewal_reminder")
async def create_renewal_reminder(context, arguments: dict[str, Any]) -> dict[str, Any]:
    """Create an idempotent renewal notice-deadline reminder workflow."""
    contract_id = _uuid_arg(arguments["contract_id"], "contract_id")
    remind_before = int(arguments.get("remind_before_days") or 15)
    async with async_session_context() as session:
        contract = await session.scalar(
            select(Contract).where(
                Contract.tenant_id == context.tenant_id, Contract.id == contract_id
            )
        )
    if contract is None:
        raise not_found("contract")
    renewal = contract.renewal_date or contract.end_date
    if renewal is None:
        raise invalid("contract has no renewal or end date")
    notice_period = contract.notice_period_days or 30
    notice_deadline = renewal - timedelta(days=notice_period)
    remind_on = notice_deadline - timedelta(days=remind_before)
    return await _create_workflow(
        context=context,
        tool_name="create_renewal_reminder",
        idempotency_key=arguments["idempotency_key"],
        workflow_type=WorkflowType.RENEWAL_NEGOTIATION,
        title=f"Renewal notice reminder: {contract.contract_number}",
        description=arguments.get("notes"),
        reference_type="contract",
        reference_id=contract.id,
        arguments=arguments,
        due_at=datetime.combine(remind_on, datetime.min.time(), UTC),
        dry_run=bool(arguments.get("dry_run", True)),
        extra={
            "kind": "renewal_reminder",
            "notice_deadline_date": notice_deadline.isoformat(),
            "remind_on": remind_on.isoformat(),
            "remind_before_days": remind_before,
        },
    )


@external.tool("prepare_renewal_brief")
async def prepare_renewal_brief(context, arguments: dict[str, Any]) -> dict[str, Any]:
    """Create an idempotent renewal-preparation workflow."""
    contract_id = _uuid_arg(arguments["contract_id"], "contract_id")
    async with async_session_context() as session:
        contract = await session.scalar(
            select(Contract).where(
                Contract.tenant_id == context.tenant_id, Contract.id == contract_id
            )
        )
        if contract is None:
            raise not_found("contract")
        annual_value = await session.scalar(
            select(
                func.coalesce(
                    func.sum(
                        ContractTermsVersion.unit_price
                        * func.coalesce(
                            ContractTermsVersion.qty_max,
                            ContractTermsVersion.qty_min,
                            1,
                        )
                    ),
                    0,
                )
            ).where(
                ContractTermsVersion.tenant_id == context.tenant_id,
                ContractTermsVersion.contract_id == contract.id,
            )
        )
    sections = arguments.get("requested_sections") or [
        "commercial_position",
        "timeline",
        "utilization",
        "leverage",
    ]
    return await _create_workflow(
        context=context,
        tool_name="prepare_renewal_brief",
        idempotency_key=arguments["idempotency_key"],
        workflow_type=WorkflowType.RENEWAL_NEGOTIATION,
        title=f"Renewal brief: {contract.contract_number}",
        description=arguments.get("notes"),
        reference_type="contract",
        reference_id=contract.id,
        arguments=arguments,
        due_at=datetime.combine(
            contract.renewal_date or contract.end_date or date.today(),
            datetime.min.time(),
            UTC,
        ),
        total_steps=4,
        dry_run=bool(arguments.get("dry_run", True)),
        extra={
            "kind": "renewal_brief",
            "requested_sections": sections,
            "annual_contract_value": float(Decimal(str(annual_value or 0))),
        },
    )


@external.tool("start_human_review_workflow")
async def start_human_review_workflow(context, arguments: dict[str, Any]) -> dict[str, Any]:
    """Start an idempotent human-review workflow for a domain object."""
    assignee = (
        _uuid_arg(arguments["assignee_user_id"], "assignee_user_id")
        if arguments.get("assignee_user_id")
        else None
    )
    workflow_type = WorkflowType(arguments["workflow_type"])
    return await _create_workflow(
        context=context,
        tool_name="start_human_review_workflow",
        idempotency_key=arguments["idempotency_key"],
        workflow_type=workflow_type,
        title=f"{workflow_type.value.replace('_', ' ').title()}: {arguments['reference_type']}",
        description=arguments.get("reason"),
        reference_type=arguments["reference_type"],
        reference_id=_uuid_arg(arguments["reference_id"], "reference_id"),
        arguments=arguments,
        assignee_user_id=assignee,
        dry_run=bool(arguments.get("dry_run", True)),
        extra={"kind": "human_review"},
    )


@external.tool("send_slack_message")
async def send_slack_message(context, arguments: dict[str, Any]) -> dict[str, Any]:
    """Send an internal Slack notification with dry-run and idempotency."""
    idempotency_key = arguments["idempotency_key"]
    channel = arguments["channel"]
    text = arguments["text"]
    async with async_session_context() as session:
        existing = await _find_idempotent(session, context.tenant_id, idempotency_key)
        if existing is not None and (existing.extra or {}).get(
            "parameters_digest"
        ) != parameters_digest(arguments):
            raise ToolError(
                ErrorCode.CONFLICT,
                "idempotency_key was already used with different parameters",
            )
        if existing is not None:
            return {
                "delivered": bool((existing.extra or {}).get("delivered")),
                "status": "replayed",
                "channel": channel,
                "idempotent_replay": True,
                "dry_run": False,
                "as_of": datetime.now(UTC).isoformat(),
                "summary": f"Slack message already sent to {channel}",
            }

    if arguments.get("dry_run", True):
        return {
            "delivered": False,
            "status": "dry_run",
            "channel": channel,
            "preview": {"text": text},
            "idempotent_replay": False,
            "dry_run": True,
            "as_of": datetime.now(UTC).isoformat(),
            "summary": f"dry run: would send Slack message to {channel}",
        }

    settings = get_mcp_settings()
    if not settings.slack_bot_token:
        raise ToolError(
            ErrorCode.INTEGRATION_UNAVAILABLE,
            "Slack is not configured; no message was sent",
            details={"integration": "slack"},
        )
    async with httpx.AsyncClient(timeout=settings.slack_timeout_seconds) as client:
        response = await client.post(
            "https://slack.com/api/chat.postMessage",
            headers={"Authorization": f"Bearer {settings.slack_bot_token}"},
            json={"channel": channel, "text": text},
        )
        response.raise_for_status()
        payload = response.json()
    delivered = bool(payload.get("ok"))
    if not delivered:
        raise ToolError(
            ErrorCode.INTEGRATION_UNAVAILABLE,
            f"Slack rejected the message: {payload.get('error', 'unknown_error')}",
            retryable=True,
        )
    async with async_session_context() as session:
        session.add(
            Workflow(
                tenant_id=context.tenant_id,
                workflow_type=WorkflowType.HUMAN_REVIEW,
                title=f"Slack notification: {channel}",
                description=text,
                reference_type=None,
                reference_id=None,
                status=WorkflowStatus.APPROVED,
                current_step=1,
                total_steps=1,
                completed_at=datetime.now(UTC),
                extra={
                    "idempotency_key": idempotency_key,
                    "parameters_digest": parameters_digest(arguments),
                    "kind": "slack_message",
                    "delivered": True,
                    "channel": channel,
                    "slack_ts": payload.get("ts"),
                    "created_by_tool": "send_slack_message",
                },
            )
        )
        await session.commit()
    return {
        "delivered": True,
        "status": "sent",
        "channel": channel,
        "idempotent_replay": False,
        "dry_run": False,
        "as_of": datetime.now(UTC).isoformat(),
        "summary": f"Slack message delivered to {channel}",
    }


# ---------------------------------------------------------------------------
# High-risk tools
# ---------------------------------------------------------------------------


@external.tool("send_email")
async def send_email(context, arguments: dict[str, Any]) -> dict[str, Any]:
    """Send an email after human confirmation.

    The email body and recipients are exactly what the confirmation token
    signs; any edit after confirmation invalidates the token.
    """
    idempotency_key = arguments["idempotency_key"]
    recipients = list(arguments["to"])
    subject = arguments["subject"]
    body = arguments["body"]
    cc = list(arguments.get("cc") or [])

    if arguments.get("dry_run", True):
        return {
            "delivered": False,
            "status": "dry_run",
            "to": recipients,
            "cc": cc,
            "subject": subject,
            "preview": body[:2000],
            "requires_confirmation": True,
            "dry_run": True,
            "as_of": datetime.now(UTC).isoformat(),
            "summary": f"dry run: would email {len(recipients)} recipient(s)",
        }

    _require_confirmation(context, "send_email", arguments)

    async with async_session_context() as session:
        existing = await _find_idempotent(session, context.tenant_id, idempotency_key)
        if existing is not None and (existing.extra or {}).get(
            "parameters_digest"
        ) != parameters_digest(arguments):
            raise ToolError(
                ErrorCode.CONFLICT,
                "idempotency_key was already used with different parameters",
            )
        if existing is not None:
            return {
                "delivered": bool((existing.extra or {}).get("delivered")),
                "status": "replayed",
                "to": recipients,
                "idempotent_replay": True,
                "dry_run": False,
                "as_of": datetime.now(UTC).isoformat(),
                "summary": "email already sent for this idempotency key",
            }

    settings = get_mcp_settings()
    if not settings.smtp_host or not settings.smtp_from_address:
        raise ToolError(
            ErrorCode.INTEGRATION_UNAVAILABLE,
            "email transport is not configured; no email was sent",
            details={"integration": "smtp"},
        )

    message = EmailMessage()
    message["From"] = settings.smtp_from_address
    message["To"] = ", ".join(recipients)
    if cc:
        message["Cc"] = ", ".join(cc)
    message["Subject"] = subject
    message.set_content(body)

    def _send() -> None:
        """Blocking SMTP send executed in a worker thread."""
        with smtplib.SMTP(
            settings.smtp_host, settings.smtp_port, timeout=settings.smtp_timeout_seconds
        ) as client:
            if settings.smtp_use_tls:
                client.starttls()
            if settings.smtp_username:
                client.login(settings.smtp_username, settings.smtp_password)
            client.send_message(message)

    try:
        await asyncio.to_thread(_send)
    except Exception as exc:
        logger.error("smtp_send_failed", error_class=type(exc).__name__)
        raise ToolError(
            ErrorCode.INTEGRATION_UNAVAILABLE,
            "email transport is temporarily unavailable; no delivery was confirmed",
            retryable=True,
        ) from exc

    async with async_session_context() as session:
        session.add(
            Workflow(
                tenant_id=context.tenant_id,
                workflow_type=WorkflowType.VENDOR_ONBOARDING,
                title=f"Email sent: {subject}"[:256],
                description=body[:4000],
                reference_type=None,
                reference_id=None,
                status=WorkflowStatus.APPROVED,
                current_step=1,
                total_steps=1,
                completed_at=datetime.now(UTC),
                extra={
                    "idempotency_key": idempotency_key,
                    "parameters_digest": parameters_digest(arguments),
                    "kind": "email",
                    "delivered": True,
                    "recipients": recipients,
                    "created_by_tool": "send_email",
                },
            )
        )
        await session.commit()
    return {
        "delivered": True,
        "status": "sent",
        "to": recipients,
        "cc": cc,
        "idempotent_replay": False,
        "dry_run": False,
        "as_of": datetime.now(UTC).isoformat(),
        "summary": f"email delivered to {len(recipients)} recipient(s)",
    }


@external.tool("submit_procurement_workflow")
async def submit_procurement_workflow(context, arguments: dict[str, Any]) -> dict[str, Any]:
    """Submit a consequential procurement action after human confirmation.

    This tool records an idempotent, auditable submission. It never mutates
    invoice, contract, or purchase-order state directly: execution remains with
    procurement-core/the ERP, which owns domain approvals.
    """
    action = arguments["action"]
    reference_type = arguments["reference_type"]
    reference_id = _uuid_arg(arguments["reference_id"], "reference_id")
    idempotency_key = arguments["idempotency_key"]

    if arguments.get("dry_run", True):
        return {
            "workflow_id": str(uuid.uuid4()),
            "status": "dry_run",
            "action": action,
            "preview": {
                "reference_type": reference_type,
                "reference_id": str(reference_id),
                "parameters": arguments.get("parameters") or {},
            },
            "requires_confirmation": True,
            "dry_run": True,
            "as_of": datetime.now(UTC).isoformat(),
            "summary": f"dry run: would submit {action}",
        }

    _require_confirmation(context, "submit_procurement_workflow", arguments)

    async with async_session_context() as session:
        if reference_type == "invoice":
            invoice = await session.scalar(
                select(Invoice).where(
                    Invoice.tenant_id == context.tenant_id, Invoice.id == reference_id
                )
            )
            if invoice is None:
                raise not_found("invoice")
            reference_label = invoice.invoice_number
        elif reference_type == "contract":
            contract = await session.scalar(
                select(Contract).where(
                    Contract.tenant_id == context.tenant_id, Contract.id == reference_id
                )
            )
            if contract is None:
                raise not_found("contract")
            reference_label = contract.contract_number
        elif reference_type == "purchase_order":
            purchase_order = await session.scalar(
                select(PurchaseOrder).where(
                    PurchaseOrder.tenant_id == context.tenant_id,
                    PurchaseOrder.id == reference_id,
                )
            )
            if purchase_order is None:
                raise not_found("purchase order")
            reference_label = purchase_order.po_number
        else:
            vendor = await session.scalar(
                select(Vendor).where(
                    Vendor.tenant_id == context.tenant_id, Vendor.id == reference_id
                )
            )
            if vendor is None:
                raise not_found("vendor")
            reference_label = vendor.name

    workflow_type = _ACTION_WORKFLOW[action]
    extra = {
        "kind": "high_risk_action",
        "action": action,
        "parameters": arguments.get("parameters") or {},
        "confirmed_by_user": context.actor_id,
        "confirmation_verified": True,
        "execution_target": "erp" if get_mcp_settings().erp_base_url else "procurement_core",
    }
    return await _create_workflow(
        context=context,
        tool_name="submit_procurement_workflow",
        idempotency_key=idempotency_key,
        workflow_type=workflow_type,
        title=f"{action.replace('_', ' ').title()}: {reference_label}"[:256],
        description=f"Confirmed high-risk action {action}",
        reference_type=reference_type,
        reference_id=reference_id,
        arguments=arguments,
        dry_run=False,
        extra=extra,
    )


__all__ = ["SERVER_NAME", "SERVER_VERSION", "external"]
