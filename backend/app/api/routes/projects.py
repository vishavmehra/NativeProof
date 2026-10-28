from uuid import UUID

from fastapi import APIRouter, status

from app.api.deps import CurrentUser, Limit, Offset
from app.schemas.projects import Project, ProjectCreate, ProjectPage, ProjectUpdate
from app.services import projects

router = APIRouter(tags=["projects"])


@router.post("/projects", status_code=status.HTTP_201_CREATED, response_model=Project)
async def create_project(body: ProjectCreate, user: CurrentUser) -> Project:
    """Create a live-mode project and its brand kit in one operation."""
    return await projects.create_project(user.id, body)


@router.post("/projects/demo", status_code=status.HTTP_201_CREATED, response_model=Project)
async def create_demo_project(user: CurrentUser) -> Project:
    """Create a demo-mode project seeded with the fixture brand, campaign, and study.

    Every run in a demo project uses labeled fixtures; it never calls Qloo or an LLM provider.
    Demo scope rules (what returns 409) are in contracts/README.md section 5.
    """
    return await projects.create_demo_project(user.id)


@router.get("/projects", response_model=ProjectPage)
async def list_projects(
    user: CurrentUser, limit: Limit = 20, offset: Offset = 0, include_archived: bool = False
) -> ProjectPage:
    return await projects.list_projects(user.id, limit, offset, include_archived)


@router.get("/projects/{project_id}", response_model=Project)
async def get_project(project_id: UUID, user: CurrentUser) -> Project:
    return await projects.get_project_detail(user.id, project_id)


@router.patch("/projects/{project_id}", response_model=Project)
async def update_project(project_id: UUID, body: ProjectUpdate, user: CurrentUser) -> Project:
    return await projects.update_project(user.id, project_id, body)


@router.delete("/projects/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def archive_project(project_id: UUID, user: CurrentUser) -> None:
    """Archive (soft-delete). Research lineage is preserved; archived projects are read-only."""
    await projects.archive_project(user.id, project_id)
