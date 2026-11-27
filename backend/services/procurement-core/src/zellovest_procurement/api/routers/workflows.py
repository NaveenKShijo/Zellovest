"""Action & Approval Workflow router backed by PostgreSQL."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from zellovest_procurement.api.deps import get_db_session, get_optional_user
from zellovest_procurement.schemas.workflows import (
    WorkflowAction,
    WorkflowActionRequest,
    WorkflowCreate,
    WorkflowListResponse,
    WorkflowResponse,
    WorkflowStatus,
    WorkflowType,
)
from zellovest_shared.db.intelligence import (
    Workflow as WorkflowRow,
    WorkflowStatus as DbWorkflowStatus,
    WorkflowType as DbWorkflowType,
)
from zellovest_shared.db.models import User
from zellovest_shared.logging_conf import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/workflows", tags=["workflows"])


def _serialize_workflow(row: WorkflowRow) -> WorkflowResponse:
    """Convert a Workflow ORM row into the public API response."""
    return WorkflowResponse(
        id=row.id,
        tenant_id=row.tenant_id,
        workflow_type=WorkflowType(row.workflow_type.value),
        title=row.title,
        description=row.description,
        status=WorkflowStatus(row.status.value),
        reference_id=str(row.reference_id) if row.reference_id else None,
        reference_type=row.reference_type,
        assignee_id=str(row.assignee_user_id) if row.assignee_user_id else None,
        current_step=row.current_step,
        total_steps=row.total_steps,
        metadata=row.extra,
        created_at=row.created_at,
        updated_at=row.updated_at,
        completed_at=row.completed_at,
    )


def _parse_uuid(value: str | None) -> UUID | None:
    """Parse an optional UUID string, returning None when absent or invalid."""
    if not value:
        return None
    try:
        return UUID(str(value))
    except ValueError:
        return None


@router.post("", response_model=WorkflowResponse, status_code=status.HTTP_201_CREATED)
async def create_workflow(
    body: WorkflowCreate,
    user: User | None = Depends(get_optional_user),
    session: AsyncSession = Depends(get_db_session),
) -> WorkflowResponse:
    """Create and persist a new procurement workflow task."""
    active_tenant = (user.tenant_id if user else None) or body.tenant_id
    row = WorkflowRow(
        tenant_id=active_tenant,
        workflow_type=DbWorkflowType(body.workflow_type.value),
        title=body.title,
        description=body.description,
        reference_id=_parse_uuid(body.reference_id),
        reference_type=body.reference_type,
        assignee_user_id=_parse_uuid(body.assignee_id) or (user.id if user else None),
        status=DbWorkflowStatus.PENDING,
        current_step=1,
        total_steps=3,
        extra=body.metadata,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    logger.info("workflow_created", tenant_id=active_tenant, workflow_id=str(row.id), type=row.workflow_type.value)
    return _serialize_workflow(row)


@router.get("", response_model=WorkflowListResponse)
async def list_workflows(
    tenant_id: str | None = Query(default=None),
    workflow_type: str | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    assignee_id: str | None = Query(default=None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user: User | None = Depends(get_optional_user),
    session: AsyncSession = Depends(get_db_session),
) -> WorkflowListResponse:
    """List tenant-scoped workflows with filtering and pagination."""
    active_tenant = (user.tenant_id if user else None) or tenant_id or "default-org"
    query = select(WorkflowRow).where(WorkflowRow.tenant_id == active_tenant)

    if workflow_type and workflow_type != "all":
        try:
            query = query.where(WorkflowRow.workflow_type == DbWorkflowType(workflow_type))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=f"Invalid workflow_type: {workflow_type}") from exc

    if status_filter and status_filter != "all":
        try:
            query = query.where(WorkflowRow.status == DbWorkflowStatus(status_filter))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=f"Invalid status: {status_filter}") from exc

    assignee_uuid = _parse_uuid(assignee_id)
    if assignee_uuid is not None:
        query = query.where(WorkflowRow.assignee_user_id == assignee_uuid)

    total = (
        await session.scalar(select(func.count()).select_from(query.subquery()))
    ) or 0
    rows = (
        await session.execute(
            query.order_by(WorkflowRow.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).scalars().all()

    return WorkflowListResponse(
        workflows=[_serialize_workflow(row) for row in rows],
        total=int(total),
        page=page,
        page_size=page_size,
    )


@router.get("/{workflow_id}", response_model=WorkflowResponse)
async def get_workflow(
    workflow_id: str,
    tenant_id: str | None = Query(default=None),
    user: User | None = Depends(get_optional_user),
    session: AsyncSession = Depends(get_db_session),
) -> WorkflowResponse:
    """Get a specific tenant-scoped workflow."""
    active_tenant = (user.tenant_id if user else None) or tenant_id or "default-org"
    wf_uuid = _parse_uuid(workflow_id)
    if wf_uuid is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Workflow {workflow_id} not found")

    row = await session.scalar(
        select(WorkflowRow).where(
            WorkflowRow.id == wf_uuid,
            WorkflowRow.tenant_id == active_tenant,
        )
    )
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Workflow {workflow_id} not found")
    return _serialize_workflow(row)


@router.post("/{workflow_id}/action", response_model=WorkflowResponse)
async def perform_workflow_action(
    workflow_id: str,
    body: WorkflowActionRequest,
    tenant_id: str | None = Query(default=None),
    user: User | None = Depends(get_optional_user),
    session: AsyncSession = Depends(get_db_session),
) -> WorkflowResponse:
    """Perform a state transition on a workflow (submit, approve, reject, cancel)."""
    active_tenant = (user.tenant_id if user else None) or tenant_id or "default-org"
    wf_uuid = _parse_uuid(workflow_id)
    if wf_uuid is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Workflow {workflow_id} not found")

    row = (
        await session.execute(
            select(WorkflowRow)
            .where(
                WorkflowRow.id == wf_uuid,
                WorkflowRow.tenant_id == active_tenant,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Workflow {workflow_id} not found")

    now = datetime.now(UTC)
    if body.action == WorkflowAction.SUBMIT:
        row.status = DbWorkflowStatus.IN_PROGRESS
        row.current_step = min(row.total_steps, row.current_step + 1)
    elif body.action == WorkflowAction.APPROVE:
        row.status = DbWorkflowStatus.APPROVED
        row.current_step = row.total_steps
        row.completed_at = now
    elif body.action == WorkflowAction.REJECT:
        row.status = DbWorkflowStatus.REJECTED
        row.completed_at = now
    elif body.action == WorkflowAction.REQUEST_CHANGES:
        row.status = DbWorkflowStatus.PENDING
        row.completed_at = None
    elif body.action == WorkflowAction.CANCEL:
        row.status = DbWorkflowStatus.CANCELLED
        row.completed_at = now

    if body.comment:
        meta = dict(row.extra or {})
        history = list(meta.get("action_notes") or [])
        history.append(
            {
                "action": body.action.value,
                "comment": body.comment,
                "actor_id": str(user.id) if user else None,
                "at": now.isoformat(),
            }
        )
        meta["action_notes"] = history
        row.extra = meta

    await session.commit()
    await session.refresh(row)
    logger.info("workflow_action", tenant_id=active_tenant, workflow_id=workflow_id, action=body.action.value)
    return _serialize_workflow(row)


@router.delete("/{workflow_id}", status_code=status.HTTP_204_NO_CONTENT)
async def cancel_workflow(
    workflow_id: str,
    tenant_id: str | None = Query(default=None),
    user: User | None = Depends(get_optional_user),
    session: AsyncSession = Depends(get_db_session),
) -> None:
    """Cancel a workflow cleanly."""
    active_tenant = (user.tenant_id if user else None) or tenant_id or "default-org"
    wf_uuid = _parse_uuid(workflow_id)
    if wf_uuid is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Workflow {workflow_id} not found")

    row = (
        await session.execute(
            select(WorkflowRow)
            .where(
                WorkflowRow.id == wf_uuid,
                WorkflowRow.tenant_id == active_tenant,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Workflow {workflow_id} not found")

    row.status = DbWorkflowStatus.CANCELLED
    row.completed_at = datetime.now(UTC)
    await session.commit()
    logger.info("workflow_cancelled", tenant_id=active_tenant, workflow_id=workflow_id)
