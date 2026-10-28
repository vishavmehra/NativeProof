from uuid import UUID

from fastapi import APIRouter, status

from app.api.deps import CurrentUser, Limit, Offset
from app.schemas.profiles import CulturalProfile, CulturalProfileCreate, CulturalProfilePage, CulturalProfileUpdate
from app.schemas.runs import RunAccepted
from app.services import insights

router = APIRouter(tags=["cultural-dna"])


@router.post(
    "/projects/{project_id}/cultural-profiles", status_code=status.HTTP_202_ACCEPTED, response_model=RunAccepted
)
async def start_cultural_profile(project_id: UUID, body: CulturalProfileCreate, user: CurrentUser) -> RunAccepted:
    """Generate a Cultural DNA profile (run_type cultural_profile). The profile id arrives in Run.result."""
    return await insights.start_cultural_profile(user.id, project_id, body)


@router.get("/projects/{project_id}/cultural-profiles", response_model=CulturalProfilePage)
async def list_cultural_profiles(
    project_id: UUID, user: CurrentUser, limit: Limit = 20, offset: Offset = 0, campaign_id: UUID | None = None
) -> CulturalProfilePage:
    return await insights.list_cultural_profiles(user.id, project_id, limit, offset, campaign_id)


@router.get("/cultural-profiles/{profile_id}", response_model=CulturalProfile)
async def get_cultural_profile(profile_id: UUID, user: CurrentUser) -> CulturalProfile:
    return await insights.get_cultural_profile(user.id, profile_id)


@router.patch("/cultural-profiles/{profile_id}", response_model=CulturalProfile)
async def update_cultural_profile(profile_id: UUID, body: CulturalProfileUpdate, user: CurrentUser) -> CulturalProfile:
    return await insights.update_cultural_profile(user.id, profile_id, body)
