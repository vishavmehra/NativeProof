"""Upload security (contracts/README.md §13 Uploads).

The type comes from the content (magic bytes), sizes are bounded, stored names are server-generated, and files
are served only to their owner through the authenticated content endpoint.
"""

import hashlib
from pathlib import Path

import httpx
import pytest
from sqlalchemy import select

from app.db import models as m
from app.db.session import read_session
from app.schemas.assets import Asset, AssetPage
from tests.integration._support import API, auth, expect_error, parse, running_app
from tests.integration.journey import JAPAN, create_demo, create_live_project
from tests.integration.v2_support import IMAGES, PNG, SPOOFS, upload

ALLOWED_TYPES = {"image/png", "image/jpeg", "image/webp"}


def stored_files(qa_env: dict[str, str]) -> list[Path]:
    root = Path(qa_env["ASSET_STORAGE_DIR"])
    return [p for p in root.rglob("*") if p.is_file()] if root.exists() else []


@pytest.mark.parametrize("name", [*IMAGES])
async def test_valid_uploads_round_trip(qa_client: httpx.AsyncClient, alice: dict[str, str], name: str) -> None:
    data, content_type = IMAGES[name]
    project = await create_live_project(qa_client, alice)
    asset = parse(Asset, await upload(qa_client, alice, project.id, kind="image", filename=name, data=data, content_type=content_type), 201)
    assert asset.kind == "image" and asset.content_type in ALLOWED_TYPES
    assert asset.size_bytes == len(data) and asset.sha256 == hashlib.sha256(data).hexdigest()
    assert asset.content_url == f"{API}/assets/{asset.id}/content"
    assert parse(Asset, await qa_client.get(f"{API}/assets/{asset.id}", headers=alice)) == asset
    content = await qa_client.get(asset.content_url, headers=alice)
    assert content.status_code == 200 and content.content == data
    assert content.headers["content-type"].split(";")[0] == asset.content_type, "serve the verified type, not a guess"
    page = parse(AssetPage, await qa_client.get(f"{API}/projects/{project.id}/assets", headers=alice))
    assert [a.id for a in page.items] == [asset.id]


@pytest.mark.parametrize("spoof", sorted(SPOOFS))
async def test_magic_bytes_decide_the_type(
    qa_client: httpx.AsyncClient, qa_env: dict[str, str], alice: dict[str, str], spoof: str
) -> None:
    """A file named and labeled as PNG is refused when its bytes are not an allowed image."""
    project = await create_live_project(qa_client, alice)
    response = await upload(qa_client, alice, project.id, kind="image", filename="photo.png", data=SPOOFS[spoof], content_type="image/png")
    expect_error(response, 422, "VALIDATION_ERROR")
    assert parse(AssetPage, await qa_client.get(f"{API}/projects/{project.id}/assets", headers=alice)).total == 0
    assert stored_files(qa_env) == [], "a refused upload left a file in storage"


async def test_kind_must_match_content(qa_client: httpx.AsyncClient, alice: dict[str, str]) -> None:
    project = await create_live_project(qa_client, alice)
    for kind, filename, data, content_type in (
        ("image", "empty.png", b"", "image/png"),
        ("video", "pixel.png", PNG, "image/png"),
    ):
        expect_error(await upload(qa_client, alice, project.id, kind=kind, filename=filename, data=data, content_type=content_type), 422, "VALIDATION_ERROR")
    relabeled = await upload(qa_client, alice, project.id, kind="image", filename="photo.gif", data=PNG, content_type="image/gif")
    if relabeled.status_code == 201:
        assert relabeled.json()["content_type"] == "image/png", "the stored type must come from the bytes, not the header"
    else:
        expect_error(relabeled, 422, "VALIDATION_ERROR")


async def test_oversize_files_are_rejected(
    qa_env: dict[str, str], monkeypatch: pytest.MonkeyPatch, alice: dict[str, str]
) -> None:
    monkeypatch.setenv("MAX_IMAGE_BYTES", "1024")
    async with running_app() as app:
        project = await create_live_project(app.client, alice)
        at_limit = PNG + b"\x00" * (1024 - len(PNG))
        assert (await upload(app.client, alice, project.id, kind="image", filename="ok.png", data=at_limit, content_type="image/png")).status_code == 201
        response = await upload(app.client, alice, project.id, kind="image", filename="big.png", data=at_limit + b"\x00", content_type="image/png")
        assert response.status_code in (413, 422), f"big.png: {response.status_code}"
        expect_error(response, response.status_code, "VALIDATION_ERROR")
        assert parse(AssetPage, await app.client.get(f"{API}/projects/{project.id}/assets", headers=alice)).total == 1
    assert stored_files(qa_env) == [], "bytes live in ASSET_STORAGE_BACKEND (database/supabase), never on local disk"


@pytest.mark.parametrize(
    "filename",
    ["../../evil.png", "..\\..\\evil.png", "/etc/evil.png", "C:\\Windows\\evil.png", "evil\x00.png", "%2e%2e%2fevil.png", "x" * 300 + ".png"],
    ids=["dotdot", "dotdot-win", "absolute", "drive", "nul", "encoded", "long"],
)
async def test_filenames_cannot_escape_storage(
    qa_client: httpx.AsyncClient, qa_env: dict[str, str], alice: dict[str, str], tmp_path: Path, filename: str
) -> None:
    project = await create_live_project(qa_client, alice)
    response = await upload(qa_client, alice, project.id, kind="image", filename=filename, data=PNG, content_type="image/png")
    assert response.status_code in (201, 422), f"{filename!r}: {response.status_code} {response.text[:200]}"
    if response.status_code == 201:
        stored_name = response.json()["filename"]
        assert "/" not in stored_name and "\\" not in stored_name and "\x00" not in stored_name and not stored_name.startswith("..")
    storage = Path(qa_env["ASSET_STORAGE_DIR"]).resolve()
    async with read_session() as s:
        stored = (await s.execute(select(m.Asset.storage_name, m.Asset.id, m.Project.owner_id)
                                  .join(m.Project, m.Project.id == m.Asset.project_id))).all()
    for key, asset_id, owner_id in stored:  # the storage key is server-generated, never the client's filename
        assert key == f"{owner_id}/{asset_id}", f"stored name {key!r} is not {{owner_id}}/{{asset_id}}"
    absolute = (Path("/etc/evil.png"), Path("C:/Windows/evil.png"), Path(storage.anchor) / "etc" / "evil.png")
    stray = list(tmp_path.parent.rglob("*evil*")) + [p for p in absolute if p.exists()]
    assert not stray, f"an upload escaped the storage directory: {stray}"


async def test_assets_are_private_to_their_owner(qa_client: httpx.AsyncClient, alice: dict[str, str], bob: dict[str, str]) -> None:
    project = await create_live_project(qa_client, alice)
    asset = parse(Asset, await upload(qa_client, alice, project.id, kind="image", filename="ad.png", data=PNG, content_type="image/png"), 201)
    for path in (f"{API}/assets/{asset.id}", asset.content_url, f"{API}/projects/{project.id}/assets"):
        expect_error(await qa_client.get(path, headers=bob), 404, "NOT_FOUND")
    expect_error(
        await upload(qa_client, bob, project.id, kind="image", filename="mine.png", data=PNG, content_type="image/png"), 404, "NOT_FOUND"
    )


async def test_other_users_asset_cannot_be_scanned(qa_client: httpx.AsyncClient, alice: dict[str, str], bob: dict[str, str]) -> None:
    project = await create_live_project(qa_client, alice)
    asset = parse(Asset, await upload(qa_client, alice, project.id, kind="image", filename="ad.png", data=PNG, content_type="image/png"), 201)
    own = await create_demo(qa_client, bob)
    scan = await qa_client.post(f"{API}/campaigns/{own.campaign_id}/risk-scans", json={"market": JAPAN, "asset_ids": [str(asset.id)]}, headers=bob)
    expect_error(scan, 404, "NOT_FOUND")


async def test_asset_content_requires_authentication(qa_client: httpx.AsyncClient, alice: dict[str, str]) -> None:
    project = await create_live_project(qa_client, alice)
    asset = parse(Asset, await upload(qa_client, alice, project.id, kind="image", filename="ad.png", data=PNG, content_type="image/png"), 201)
    for headers in ({}, {"Authorization": "Bearer not-a-token"}, {"Authorization": f"Basic {asset.id}"}):
        expect_error(await qa_client.get(asset.content_url, headers=headers), 401, "UNAUTHENTICATED")
    expect_error(
        await qa_client.post(f"{API}/projects/{project.id}/assets", files={"file": ("a.png", PNG, "image/png")}, data={"kind": "image"}),
        401,
        "UNAUTHENTICATED",
    )
    assert (await qa_client.get(asset.content_url, headers=auth("qa-alice"))).status_code == 200
