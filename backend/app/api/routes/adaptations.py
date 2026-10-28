from uuid import UUID

from fastapi import APIRouter, status

from app.api.deps import CurrentUser, Limit, Offset
from app.schemas.adaptations import Adaptation, AdaptationCreate, AdaptationPage, AdaptationRevisionCreate
from app.schemas.runs import RunAccepted
from app.services import adaptations, results, runs

router = APIRouter(tags=["voice"])


@router.post(
    "/campaigns/{campaign_id}/adaptations", status_code=status.HTTP_202_ACCEPTED, response_model=RunAccepted
)
async def start_adaptation(campaign_id: UUID, body: AdaptationCreate, user: CurrentUser) -> RunAccepted:
    """Start a Voice adaptation run (run_type campaign_adaptation)."""
    return await runs.start_adaptation(user.id, campaign_id, body)


@router.get("/campaigns/{campaign_id}/adaptations", response_model=AdaptationPage)
async def list_adaptations(
    campaign_id: UUID, user: CurrentUser, limit: Limit = 20, offset: Offset = 0, run_id: UUID | None = None
) -> AdaptationPage:
    return await results.list_adaptations(user.id, campaign_id, limit, offset, run_id)


@router.get("/adaptations/{adaptation_id}", response_model=Adaptation)
async def get_adaptation(adaptation_id: UUID, user: CurrentUser) -> Adaptation:
    return await results.get_adaptation(user.id, adaptation_id)


@router.post(
    "/adaptations/{adaptation_id}/revisions", status_code=status.HTTP_201_CREATED, response_model=Adaptation
)
async def create_adaptation_revision(
    adaptation_id: UUID, body: AdaptationRevisionCreate, user: CurrentUser
) -> Adaptation:
    return await adaptations.create_revision(user.id, adaptation_id, body)
