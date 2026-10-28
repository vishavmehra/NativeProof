from uuid import UUID

from fastapi import APIRouter, status

from app.api.deps import CurrentUser, Limit, Offset
from app.schemas.runs import RunAccepted
from app.schemas.studies import RehearsalCreate, RehearsalResult, Study, StudyCreate, StudyPage
from app.services import results, runs, studies

router = APIRouter(tags=["audience"])


@router.post("/projects/{project_id}/studies", status_code=status.HTTP_201_CREATED, response_model=Study)
async def create_study(project_id: UUID, body: StudyCreate, user: CurrentUser) -> Study:
    return await studies.create_study(user.id, project_id, body)


@router.get("/projects/{project_id}/studies", response_model=StudyPage)
async def list_studies(
    project_id: UUID, user: CurrentUser, limit: Limit = 20, offset: Offset = 0, campaign_id: UUID | None = None
) -> StudyPage:
    return await studies.list_studies(user.id, project_id, limit, offset, campaign_id)


@router.get("/studies/{study_id}", response_model=Study)
async def get_study(study_id: UUID, user: CurrentUser) -> Study:
    return await studies.get_study(user.id, study_id)


@router.post("/studies/{study_id}/rehearsals", status_code=status.HTTP_202_ACCEPTED, response_model=RunAccepted)
async def start_rehearsal(study_id: UUID, body: RehearsalCreate, user: CurrentUser) -> RunAccepted:
    """Start an Audience rehearsal run (run_type campaign_rehearsal). Send {} to use study defaults."""
    return await runs.start_rehearsal(user.id, study_id, body)


@router.get("/studies/{study_id}/rehearsals/{run_id}", response_model=RehearsalResult)
async def get_rehearsal(study_id: UUID, run_id: UUID, user: CurrentUser) -> RehearsalResult:
    return await results.get_rehearsal(user.id, study_id, run_id)
