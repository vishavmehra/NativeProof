from uuid import UUID

from fastapi import APIRouter, status

from app.api.deps import CurrentUser, Limit, Offset
from app.schemas.campaigns import Campaign, CampaignCreate, CampaignPage, CampaignUpdate
from app.services import campaigns

router = APIRouter(tags=["campaigns"])


@router.post("/projects/{project_id}/campaigns", status_code=status.HTTP_201_CREATED, response_model=Campaign)
async def create_campaign(project_id: UUID, body: CampaignCreate, user: CurrentUser) -> Campaign:
    """Create the campaign and its first content version."""
    return await campaigns.create_campaign(user.id, project_id, body)


@router.get("/projects/{project_id}/campaigns", response_model=CampaignPage)
async def list_campaigns(project_id: UUID, user: CurrentUser, limit: Limit = 20, offset: Offset = 0) -> CampaignPage:
    return await campaigns.list_campaigns(user.id, project_id, limit, offset)


@router.get("/campaigns/{campaign_id}", response_model=Campaign)
async def get_campaign(campaign_id: UUID, user: CurrentUser) -> Campaign:
    return await campaigns.get_campaign(user.id, campaign_id)


@router.patch("/campaigns/{campaign_id}", response_model=Campaign)
async def update_campaign(campaign_id: UUID, body: CampaignUpdate, user: CurrentUser) -> Campaign:
    return await campaigns.update_campaign(user.id, campaign_id, body)
