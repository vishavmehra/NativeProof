from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, File, Form, Response, UploadFile, status

from app.api.deps import CurrentUser, Limit, Offset
from app.services import assets as service
from app.schemas.assets import Asset, AssetKind, AssetPage

router = APIRouter(tags=["assets"])


@router.post("/projects/{project_id}/assets", status_code=status.HTTP_201_CREATED, response_model=Asset)
async def upload_asset(
    project_id: UUID,
    user: CurrentUser,
    file: Annotated[UploadFile, File()],
    kind: Annotated[AssetKind, Form()],
) -> Asset:
    """Upload an image creative. Type and size are validated (contracts/README section 13)."""
    data = await file.read(service.max_bytes() + 1)  # bounded read; oversize is rejected by the service
    return await service.upload_asset(user.id, project_id, kind, file.filename, data)


@router.get("/projects/{project_id}/assets", response_model=AssetPage)
async def list_assets(
    project_id: UUID, user: CurrentUser, limit: Limit = 20, offset: Offset = 0, kind: AssetKind | None = None
) -> AssetPage:
    return await service.list_assets(user.id, project_id, limit, offset, kind)


@router.get("/assets/{asset_id}", response_model=Asset)
async def get_asset(asset_id: UUID, user: CurrentUser) -> Asset:
    return await service.get_asset(user.id, asset_id)


@router.get(
    "/assets/{asset_id}/content",
    response_class=Response,
    responses={200: {"description": "The file bytes.", "content": {"image/*": {}}}},
)
async def get_asset_content(asset_id: UUID, user: CurrentUser) -> Response:
    return await service.asset_content(user.id, asset_id)
