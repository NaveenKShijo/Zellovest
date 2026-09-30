"""Action & Approval Workflow router."""

from datetime import UTC, datetime
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from zellovest_procurement.api.deps import get_db_session
from zellovest_procurement.schemas.workflows import (
    WorkflowActionRequest,
    WorkflowCreate,
    WorkflowListResponse,
    WorkflowResponse,
    WorkflowStatus,
)
from zellovest_shared.logging_conf import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/workflows", tags=["workflows"])


@router.post("", response_model=WorkflowResponse, status_code=status.HTTP_201_CREATED)
async def create_workflow(
    body: WorkflowCreate,
    session: AsyncSession = Depends(get_db_session),
) -> WorkflowResponse:
    """Create a new workflow."""
    logger.info("workflow_created", tenant_id=body.tenant_id, type=body.workflow_type.value)
    now = datetime.now(UTC)
    return WorkflowResponse(
        id=uuid4(),
        tenant_id=body.tenant_id,
        workflow_type=body.workflow_type,
        title=body.title,
        description=body.description,
        status=WorkflowStatus.PENDING,
        reference_id=body.reference_id,
        reference_type=body.reference_type,
        assignee_id=body.assignee_id,
        current_step=1,
        total_steps=3,
        metadata=body.metadata,
        created_at=now,
        updated_at=now,
    )


@router.get("", response_model=WorkflowListResponse)
async def list_workflows(
    tenant_id: str = Query(..., min_length=1),
    workflow_type: str | None = Query(default=None),
    status: str | None = Query(default=None),
    assignee_id: str | None = Query(default=None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    session: AsyncSession = Depends(get_db_session),
) -> WorkflowListResponse:
    """List workflows with filtering and pagination."""
    logger.info("workflows_listed", tenant_id=tenant_id)
    return WorkflowListResponse(
        workflows=[],
        total=0,
        page=page,
        page_size=page_size,
    )


@router.get("/{workflow_id}", response_model=WorkflowResponse)
async def get_workflow(
    workflow_id: str,
    tenant_id: str = Query(..., min_length=1),
    session: AsyncSession = Depends(get_db_session),
) -> WorkflowResponse:
    """Get a specific workflow."""
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"Workflow {workflow_id} not found",
    )


@router.post("/{workflow_id}/action", response_model=WorkflowResponse)
async def perform_workflow_action(
    workflow_id: str,
    body: WorkflowActionRequest,
    tenant_id: str = Query(..., min_length=1),
    session: AsyncSession = Depends(get_db_session),
) -> WorkflowResponse:
    """Perform an action on a workflow (approve, reject, etc.)."""
    logger.info("workflow_action", workflow_id=workflow_id, action=body.action.value)
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"Workflow {workflow_id} not found",
    )


@router.delete("/{workflow_id}", status_code=status.HTTP_204_NO_CONTENT)
async def cancel_workflow(
    workflow_id: str,
    tenant_id: str = Query(..., min_length=1),
    session: AsyncSession = Depends(get_db_session),
) -> None:
    """Cancel a workflow."""
    logger.info("workflow_cancelled", workflow_id=workflow_id)