from uuid import UUID

from fastapi import APIRouter, status

from app.api.deps import CurrentUser, Limit, Offset
from app.schemas.arena import ArenaCreate, ArenaPage, ArenaResult, ArenaUpdate
from app.schemas.runs import RunAccepted
from app.services import insights

router = APIRouter(tags=["campaign-arena"])


@router.post("/campaigns/{campaign_id}/arenas", status_code=status.HTTP_202_ACCEPTED, response_model=RunAccepted)
async def start_arena(campaign_id: UUID, body: ArenaCreate, user: CurrentUser) -> RunAccepted:
    """Compare variants under the same segments and criteria (run_type campaign_arena)."""
    return await insights.start_arena(user.id, campaign_id, body)


@router.get("/campaigns/{campaign_id}/arenas", response_model=ArenaPage)
async def list_arenas(campaign_id: UUID, user: CurrentUser, limit: Limit = 20, offset: Offset = 0) -> ArenaPage:
    return await insights.list_arenas(user.id, campaign_id, limit, offset)


@router.get("/arenas/{arena_id}", response_model=ArenaResult)
async def get_arena(arena_id: UUID, user: CurrentUser) -> ArenaResult:
    return await insights.get_arena(user.id, arena_id)


@router.patch("/arenas/{arena_id}", response_model=ArenaResult)
async def update_arena(arena_id: UUID, body: ArenaUpdate, user: CurrentUser) -> ArenaResult:
    return await insights.update_arena(user.id, arena_id, body)
