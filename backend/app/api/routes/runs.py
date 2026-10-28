from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, status

from app.api.deps import CurrentUser, Limit, Offset
from app.schemas.runs import Run, RunAccepted, RunPage, RunStatus, RunType
from app.services import runs
from app.services import results

router = APIRouter(tags=["runs"])


@router.get("/runs/{run_id}", response_model=Run)
async def get_run(run_id: UUID, user: CurrentUser) -> Run:
    return await results.get_run(user.id, run_id)


@router.get("/projects/{project_id}/runs", response_model=RunPage)
async def list_runs(
    project_id: UUID,
    user: CurrentUser,
    limit: Limit = 20,
    offset: Offset = 0,
    run_type: RunType | None = None,
    campaign_id: UUID | None = None,
    study_id: UUID | None = None,
    run_status: Annotated[RunStatus | None, Query(alias="status")] = None,
) -> RunPage:
    """Newest first."""
    return await results.list_runs(user.id, project_id, limit, offset, run_type, campaign_id, study_id, run_status)


@router.post("/runs/{run_id}/cancel", response_model=Run)
async def cancel_run(run_id: UUID, user: CurrentUser) -> Run:
    """Cooperative cancel: stops at the next checkpoint; saved partial work stays (README §14.5). 409 if terminal."""
    return await runs.cancel_run(user.id, run_id)


@router.post("/runs/{run_id}/resume", status_code=status.HTTP_202_ACCEPTED, response_model=RunAccepted)
async def resume_run(run_id: UUID, user: CurrentUser) -> RunAccepted:
    """Resume an interrupted or failed population_study/social_simulation from its last checkpoint (README §14.5).
    409 for other run types or runs without a checkpoint."""
    return await runs.resume_run(user.id, run_id)
