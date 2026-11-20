"""HTTP entry point for the Procurement Investigation Agent."""

from fastapi import APIRouter, Depends, HTTPException, Request
from zellovest_shared.db.models import User

from zellovest_agentic.api.deps import build_mcp_identity, get_current_user
from zellovest_agentic.schemas.investigation import ReconciliationInvestigationResponse

router = APIRouter(prefix="/investigations", tags=["investigations"])


@router.post("/reconciliation/{exception_id}", response_model=ReconciliationInvestigationResponse)
async def investigate_reconciliation_exception(
    exception_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
) -> ReconciliationInvestigationResponse:
    """Investigate one AP exception through the controlled MCP tool boundary."""
    agent = getattr(request.app.state, "investigation_agent", None)
    if agent is None:
        raise HTTPException(status_code=503, detail="investigation service is unavailable")
    identity = build_mcp_identity(current_user, request.state.request_id)
    return await agent.investigate(exception_id, identity)
