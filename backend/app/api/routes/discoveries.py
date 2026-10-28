from uuid import UUID

from fastapi import APIRouter, status

from app.api.deps import CurrentUser
from app.schemas.discovery import DiscoveryCreate, DiscoveryResult
from app.schemas.runs import RunAccepted
from app.services import results, runs

router = APIRouter(tags=["atlas"])


@router.post(
    "/projects/{project_id}/discoveries", status_code=status.HTTP_202_ACCEPTED, response_model=RunAccepted
)
async def start_discovery(project_id: UUID, body: DiscoveryCreate, user: CurrentUser) -> RunAccepted:
    """Start an Atlas market-discovery run (run_type market_discovery)."""
    return await runs.start_discovery(user.id, project_id, body)


@router.get("/projects/{project_id}/discoveries/{run_id}", response_model=DiscoveryResult)
async def get_discovery(project_id: UUID, run_id: UUID, user: CurrentUser) -> DiscoveryResult:
    return await results.get_discovery(user.id, project_id, run_id)
