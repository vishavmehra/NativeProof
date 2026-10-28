from uuid import UUID

from fastapi import APIRouter, status

from app.api.deps import CurrentUser
from app.schemas.evaluations import EvaluationCreate, EvaluationResult
from app.schemas.runs import RunAccepted
from app.services import results, runs

router = APIRouter(tags=["loop"])


@router.post(
    "/campaigns/{campaign_id}/evaluations", status_code=status.HTTP_202_ACCEPTED, response_model=RunAccepted
)
async def start_evaluation(campaign_id: UUID, body: EvaluationCreate, user: CurrentUser) -> RunAccepted:
    """Start a Loop evaluation run (run_type campaign_evaluation). The result id arrives in Run.result."""
    return await runs.start_evaluation(user.id, campaign_id, body)


@router.get("/campaigns/{campaign_id}/evaluations/{evaluation_id}", response_model=EvaluationResult)
async def get_evaluation(campaign_id: UUID, evaluation_id: UUID, user: CurrentUser) -> EvaluationResult:
    return await results.get_evaluation(user.id, campaign_id, evaluation_id)
