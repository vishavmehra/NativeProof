from uuid import UUID

from fastapi import APIRouter, status

from app.api.deps import CurrentUser, Limit, Offset
from app.schemas.markets import MarketComparison, MarketComparisonCreate, MarketComparisonPage
from app.schemas.runs import RunAccepted
from app.services import insights

router = APIRouter(tags=["market-expansion"])


@router.post(
    "/projects/{project_id}/market-comparisons", status_code=status.HTTP_202_ACCEPTED, response_model=RunAccepted
)
async def start_market_comparison(project_id: UUID, body: MarketComparisonCreate, user: CurrentUser) -> RunAccepted:
    """Compare markets with the Atlas pipeline (run_type market_comparison)."""
    return await insights.start_market_comparison(user.id, project_id, body)


@router.get("/projects/{project_id}/market-comparisons", response_model=MarketComparisonPage)
async def list_market_comparisons(
    project_id: UUID, user: CurrentUser, limit: Limit = 20, offset: Offset = 0
) -> MarketComparisonPage:
    return await insights.list_market_comparisons(user.id, project_id, limit, offset)


@router.get("/market-comparisons/{comparison_id}", response_model=MarketComparison)
async def get_market_comparison(comparison_id: UUID, user: CurrentUser) -> MarketComparison:
    return await insights.get_market_comparison(user.id, comparison_id)
