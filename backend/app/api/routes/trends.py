from uuid import UUID

from fastapi import APIRouter, status

from app.api.deps import CurrentUser, Limit, Offset
from app.schemas.trends import (
    Snapshot,
    SnapshotCreate,
    SnapshotPage,
    TrendComparison,
    TrendComparisonCreate,
    TrendComparisonPage,
)
from app.services import trends

router = APIRouter(tags=["trend-watch"])


@router.post("/projects/{project_id}/snapshots", status_code=status.HTTP_201_CREATED, response_model=Snapshot)
async def create_snapshot(project_id: UUID, body: SnapshotCreate, user: CurrentUser) -> Snapshot:
    return await trends.create_snapshot(user.id, project_id, body)


@router.get("/projects/{project_id}/snapshots", response_model=SnapshotPage)
async def list_snapshots(
    project_id: UUID, user: CurrentUser, limit: Limit = 20, offset: Offset = 0, campaign_id: UUID | None = None
) -> SnapshotPage:
    return await trends.list_snapshots(user.id, project_id, limit, offset, campaign_id)


@router.post(
    "/projects/{project_id}/trend-comparisons", status_code=status.HTTP_201_CREATED, response_model=TrendComparison
)
async def create_trend_comparison(project_id: UUID, body: TrendComparisonCreate, user: CurrentUser) -> TrendComparison:
    """Deterministic, synchronous diff of two snapshots of the same project."""
    return await trends.create_trend_comparison(user.id, project_id, body)


@router.get("/projects/{project_id}/trend-comparisons", response_model=TrendComparisonPage)
async def list_trend_comparisons(
    project_id: UUID, user: CurrentUser, limit: Limit = 20, offset: Offset = 0
) -> TrendComparisonPage:
    return await trends.list_trend_comparisons(user.id, project_id, limit, offset)


@router.get("/trend-comparisons/{comparison_id}", response_model=TrendComparison)
async def get_trend_comparison(comparison_id: UUID, user: CurrentUser) -> TrendComparison:
    return await trends.get_trend_comparison(user.id, comparison_id)
