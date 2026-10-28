"""Uploaded image creatives and the visual observations a vision model reports about them."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field

from app.schemas.common import ApiModel, Page

AssetKind = Literal["image"]


class Asset(ApiModel):
    id: UUID
    project_id: UUID
    kind: AssetKind
    filename: str
    content_type: str
    size_bytes: int
    sha256: str
    created_at: datetime
    content_url: str = Field(description="Authenticated API path that streams the file.")


class AssetPage(Page[Asset]):
    pass


class VisualObservation(ApiModel):
    """Something visibly present in an image, as reported by a vision model. Not an interpretation."""

    id: str
    asset_id: UUID
    kind: Literal["object", "text_in_image", "symbol", "person", "color_or_layout", "other"]
    description: str
    location: str | None = Field(description="Approximate position such as top-left; null when not reported.")


class VisionStatus(ApiModel):
    status: Literal["analyzed", "not_requested", "unavailable", "failed"]
    provider: str | None
    model_id: str | None
    message: str | None = Field(
        description="Why vision was unavailable or failed. Images are never passed to a text-only model instead."
    )
