"""Workflow schemas."""

from datetime import datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, Field


class WorkflowType(str, Enum):
    """Workflow types."""

    INVOICE_APPROVAL = "invoice_approval"
    CONTRACT_REVIEW = "contract_review"
    VENDOR_ONBOARDING = "vendor_onboarding"
    PURCHASE_ORDER_APPROVAL = "purchase_order_approval"
    RENEWAL_NEGOTIATION = "renewal_negotiation"


class WorkflowStatus(str, Enum):
    """Workflow status."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    APPROVED = "approved"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


class WorkflowAction(str, Enum):
    """Workflow actions."""

    SUBMIT = "submit"
    APPROVE = "approve"
    REJECT = "reject"
    REQUEST_CHANGES = "request_changes"
    CANCEL = "cancel"


class WorkflowCreate(BaseModel):
    """Request to create a new workflow."""

    tenant_id: str = Field(..., min_length=1, max_length=128)
    workflow_type: WorkflowType
    title: str = Field(..., min_length=1, max_length=256)
    description: str | None = None
    reference_id: str | None = None  # e.g., invoice_id, contract_id
    reference_type: str | None = None  # e.g., "invoice", "contract"
    assignee_id: str | None = None
    metadata: dict | None = None


class WorkflowActionRequest(BaseModel):
    """Request to perform an action on a workflow."""

    action: WorkflowAction
    comment: str | None = None


class WorkflowResponse(BaseModel):
    """Workflow information response."""

    id: UUID
    tenant_id: str
    workflow_type: WorkflowType
    title: str
    description: str | None
    status: WorkflowStatus
    reference_id: str | None
    reference_type: str | None
    assignee_id: str | None
    current_step: int
    total_steps: int
    metadata: dict | None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None


class WorkflowListResponse(BaseModel):
    """Paginated workflow list response."""

    workflows: list[WorkflowResponse]
    total: int
    page: int
    page_size: int