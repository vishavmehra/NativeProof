from uuid import UUID

from fastapi import APIRouter

from app.api.deps import CurrentUser
from app.schemas.projects import Brand, BrandUpdate
from app.services import projects

router = APIRouter(tags=["brand-memory"])


@router.get("/projects/{project_id}/brand", response_model=Brand)
async def get_brand(project_id: UUID, user: CurrentUser) -> Brand:
    return await projects.get_brand(user.id, project_id)


@router.put("/projects/{project_id}/brand", response_model=Brand)
async def update_brand(project_id: UUID, body: BrandUpdate, user: CurrentUser) -> Brand:
    """Replace the user-approved Brand Memory. Only people write here. Demo projects return 409."""
    return await projects.replace_brand(user.id, project_id, body)
