"""Uploaded image assets (contracts/README §13, D-035).

Uploads are typed by their magic bytes, not by filename or header, size-limited, and stored
under server-generated keys `{owner_id}/{asset_id}` in the ASSET_STORAGE_BACKEND (app/db/blobs.py).
"""

import hashlib
import unicodedata
from pathlib import Path, PureWindowsPath
from uuid import UUID, uuid4

from fastapi.responses import Response
from sqlalchemy import select

from app.core.config import get_settings
from app.core.errors import ValidationFailed
from app.db import blobs
from app.db import models as m
from app.db.base import utcnow
from app.db.session import session
from app.schemas.assets import Asset, AssetKind, AssetPage
from app.schemas.common import ErrorDetail
from app.services.common import get_owned, get_project, not_found, paginate, touch

ALLOWED = {"image": "PNG, JPEG, or WebP"}


def sniff(data: bytes) -> tuple[AssetKind, str, str] | None:
    """(kind, content type, extension) from the file's magic bytes, or None for anything else."""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image", "image/png", "png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image", "image/jpeg", "jpg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image", "image/webp", "webp"
    return None


def safe_filename(name: str | None) -> str:
    """Display name only: no directories or control characters. Never used as a storage path."""
    base = PureWindowsPath(Path(name or "").name).name  # strips both / and \ directory parts
    cleaned = "".join(ch for ch in base if unicodedata.category(ch)[0] != "C").strip()
    return cleaned[:200] or "upload"


def to_asset(row: m.Asset) -> Asset:
    return Asset(
        id=row.id, project_id=row.project_id, kind=row.kind, filename=row.filename,  # type: ignore[arg-type]
        content_type=row.content_type, size_bytes=row.size_bytes, sha256=row.sha256, created_at=row.created_at,
        content_url=f"/api/v1/assets/{row.id}/content",
    )


def _invalid(message: str, field: str = "file") -> ValidationFailed:
    return ValidationFailed(message, details=[ErrorDetail(field=field, message=message)])


def max_bytes() -> int:
    return get_settings().max_image_bytes


async def upload_asset(user_id: UUID, project_id: UUID, kind: AssetKind, filename: str | None, data: bytes) -> Asset:
    """`data` must already be bounded by the caller to max_bytes() + 1."""
    async with session() as s:
        await get_project(s, user_id, project_id, writable=True)
    limit = max_bytes()
    if not data:
        raise _invalid("The file is empty.")
    if len(data) > limit:
        raise _invalid(f"The file is larger than the {limit // (1024 * 1024)} MB limit for {kind} uploads.")
    detected = sniff(data)
    if detected is None or detected[0] != kind:
        raise _invalid(f"The file content is not a supported {kind} format ({ALLOWED[kind]}).")
    _, content_type, _ = detected
    asset_id = uuid4()
    storage_name = blobs.object_key(user_id, asset_id)
    await blobs.store(storage_name, data, content_type)  # supabase: uploaded now; database: committed with the row below
    try:
        async with session() as s, s.begin():
            project = await get_project(s, user_id, project_id, writable=True)
            row = m.Asset(
                id=asset_id, project_id=project_id, kind=kind, filename=safe_filename(filename), content_type=content_type,
                size_bytes=len(data), sha256=hashlib.sha256(data).hexdigest(), storage_name=storage_name, created_at=utcnow(),
            )
            s.add(row)
            blobs.attach(s, row, data)
            touch(project)
    except BaseException:
        await blobs.discard([storage_name])
        raise
    return to_asset(row)


async def list_assets(user_id: UUID, project_id: UUID, limit: int, offset: int, kind: AssetKind | None) -> AssetPage:
    async with session() as s:
        await get_project(s, user_id, project_id)
        stmt = select(m.Asset).where(m.Asset.project_id == project_id)
        if kind is not None:
            stmt = stmt.where(m.Asset.kind == kind)
        rows, total = await paginate(s, stmt.order_by(m.Asset.created_at.desc(), m.Asset.id), limit, offset)
    return AssetPage(items=[to_asset(row) for row in rows], limit=limit, offset=offset, total=total)


async def get_asset(user_id: UUID, asset_id: UUID) -> Asset:
    async with session() as s:
        row, _ = await get_owned(s, m.Asset, asset_id, user_id, "Asset")
    return to_asset(row)


async def asset_content(user_id: UUID, asset_id: UUID) -> Response:
    async with session() as s:
        row, _ = await get_owned(s, m.Asset, asset_id, user_id, "Asset")
    return await blobs.content_response(row)
