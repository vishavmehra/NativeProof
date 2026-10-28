"""Image assets over HTTP (contracts/README §13). No provider is called."""

from typing import Any

import httpx
import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.db import models as m
from app.db.session import read_session
from tests.conftest import BOB

API = "/api/v1"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
WAV = b"RIFF\x24\x00\x00\x00WAVEfmt " + b"\x00" * 100


async def stored() -> list[str]:
    """Storage keys of every stored asset, each as `{owner_id}/{asset_id}` when its bytes exist."""
    async with read_session() as s:
        rows = (await s.execute(select(m.Asset.storage_name, m.Project.owner_id, m.Asset.id, m.AssetBlob.asset_id)
                                .join(m.Project, m.Project.id == m.Asset.project_id)
                                .outerjoin(m.AssetBlob, m.AssetBlob.asset_id == m.Asset.id))).all()
    assert all(key == f"{owner}/{asset_id}" and blob == asset_id for key, owner, asset_id, blob in rows)
    return [key for key, *_ in rows]


async def live_project(client: httpx.AsyncClient) -> str:
    return (await client.post(f"{API}/projects", json={"name": "P", "brand_name": "B"})).json()["id"]


async def upload(client: httpx.AsyncClient, project_id: str, kind: str, data: bytes, name: str = "file.bin",
                 **kwargs: Any) -> httpx.Response:
    return await client.post(f"{API}/projects/{project_id}/assets", files={"file": (name, data, "application/octet-stream")},
                             data={"kind": kind}, **kwargs)


async def test_upload_list_get_and_stream_an_image(client: httpx.AsyncClient) -> None:
    project_id = await live_project(client)
    response = await upload(client, project_id, "image", PNG, name="../../creative.png")
    assert response.status_code == 201, response.text
    asset = response.json()
    assert (asset["kind"], asset["content_type"], asset["size_bytes"], asset["filename"]) == (
        "image", "image/png", len(PNG), "creative.png")
    assert asset["content_url"] == f"/api/v1/assets/{asset['id']}/content"
    assert [key.split("/")[1] for key in await stored()] == [asset["id"]]  # server-generated key, never the filename

    assert (await client.get(f"{API}/assets/{asset['id']}")).json() == asset
    content = await client.get(asset["content_url"])
    assert content.status_code == 200 and content.content == PNG
    assert content.headers["content-type"] == "image/png" and content.headers["x-content-type-options"] == "nosniff"
    page = (await client.get(f"{API}/projects/{project_id}/assets")).json()
    assert page["total"] == 1 and page["items"][0]["id"] == asset["id"]
    assert (await client.get(f"{API}/projects/{project_id}/assets", params={"kind": "image"})).json()["total"] == 1


@pytest.mark.parametrize(
    ("kind", "data"),
    [("image", WAV), ("image", b"plain text pretending to be a png"), ("image", b""),
     ("image", b"GIF89a" + b"\x00" * 20)],
    ids=["wav-as-image", "text", "empty", "gif"],
)
async def test_type_is_checked_from_magic_bytes(client: httpx.AsyncClient, kind: str, data: bytes) -> None:
    project_id = await live_project(client)
    response = await upload(client, project_id, kind, data, name="looks-fine.png")
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert await stored() == []


async def test_audio_uploads_are_not_accepted(client: httpx.AsyncClient) -> None:
    project_id = await live_project(client)
    response = await upload(client, project_id, "audio", WAV, name="brief.wav")
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert await stored() == []


async def test_image_size_limit_applies(client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAX_IMAGE_BYTES", "64")
    get_settings.cache_clear()
    project_id = await live_project(client)
    response = await upload(client, project_id, "image", PNG)
    assert response.status_code == 422 and "limit" in response.json()["error"]["message"]


async def test_other_users_get_404(client: httpx.AsyncClient) -> None:
    project_id = await live_project(client)
    image = (await upload(client, project_id, "image", PNG)).json()
    for request in (
        client.get(f"{API}/assets/{image['id']}", headers=BOB),
        client.get(f"{API}/assets/{image['id']}/content", headers=BOB),
        client.get(f"{API}/projects/{project_id}/assets", headers=BOB),
        upload(client, project_id, "image", PNG, headers=BOB),
    ):
        response = await request
        assert response.status_code == 404, response.text
