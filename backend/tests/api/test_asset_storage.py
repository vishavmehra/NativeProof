"""ASSET_STORAGE_BACKEND: the database fallback and Supabase Storage (an httpx.MockTransport; no network)."""

import json
import logging

import httpx
import pytest
from pydantic import ValidationError
from sqlalchemy import func, select

from app.core.config import Settings, get_settings
from app.core.logging import JsonFormatter, _secret_values
from app.db import blobs
from app.db import models as m
from app.db.session import read_session
from tests.api.test_crud import make_project
from tests.conftest import BOB

API = "/api/v1"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + bytes(64)
SECRET = "sb_secret_TEST-ONLY-not-a-real-key-0123456789"
PROVIDER_DETAIL = "upstream detail that must never reach a client"


class FakeStorage:
    """The Storage REST endpoints the backend uses; `fail` queues status codes or exception types, one per request."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.requests: list[httpx.Request] = []
        self.fail: list[int | type[httpx.TransportError]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        assert request.headers["apikey"] == SECRET and request.headers["authorization"] == f"Bearer {SECRET}"
        if self.fail:
            failure = self.fail.pop(0)
            if isinstance(failure, int):
                return httpx.Response(failure, json={"message": PROVIDER_DETAIL})
            raise failure(PROVIDER_DETAIL, request=request)
        key = request.url.path.removeprefix("/storage/v1/object/assets").lstrip("/")
        if request.method == "POST":
            assert request.headers["x-upsert"] == "false"
            self.objects[key] = request.content
            return httpx.Response(200, json={"Key": f"assets/{key}"})
        if request.method == "GET":
            if key not in self.objects:  # what Storage answers for a missing object
                return httpx.Response(400, json={"statusCode": "404", "error": "not_found", "message": "Object not found"})
            return httpx.Response(200, content=self.objects[key])
        removed = [k for k in json.loads(request.content)["prefixes"] if self.objects.pop(k, None) is not None]
        return httpx.Response(200, json=[{"name": k} for k in removed])


def use(monkeypatch: pytest.MonkeyPatch, **env: str) -> None:
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    get_settings.cache_clear()


@pytest.fixture
def storage(test_settings: None, monkeypatch: pytest.MonkeyPatch) -> FakeStorage:
    fake = FakeStorage()
    use(monkeypatch, ASSET_STORAGE_BACKEND="supabase", SUPABASE_URL="https://project.supabase.example",
        SUPABASE_SECRET_KEY=SECRET)
    monkeypatch.setattr(blobs, "_transport", httpx.MockTransport(fake))
    monkeypatch.setattr(blobs, "BACKOFF", (0, 0))
    return fake


async def upload(client: httpx.AsyncClient, project_id: str, **kwargs: object) -> httpx.Response:
    return await client.post(f"{API}/projects/{project_id}/assets", data={"kind": "image"},
                             files={"file": ("../../photo.png", PNG, "image/png")}, **kwargs)  # type: ignore[arg-type]


async def rows() -> tuple[list[tuple[str, object]], int]:
    """(storage_name, owner) per asset, and the number of database blobs."""
    async with read_session() as s:
        assets = (await s.execute(select(m.Asset.storage_name, m.Project.owner_id)
                                  .join(m.Project, m.Project.id == m.Asset.project_id))).all()
        return [tuple(a) for a in assets], int(await s.scalar(select(func.count()).select_from(m.AssetBlob)) or 0)


async def test_database_backend_round_trip_and_isolation(client: httpx.AsyncClient) -> None:
    project = await make_project(client)
    asset = (await upload(client, project["id"])).json()
    content = await client.get(asset["content_url"])
    assert content.status_code == 200 and content.content == PNG
    assert content.headers["content-type"] == "image/png" and content.headers["x-content-type-options"] == "nosniff"
    (key, owner), = (await rows())[0]
    assert key == f"{owner}/{asset['id']}" and (await rows())[1] == 1
    assert (await client.get(f"{API}/assets/{asset['id']}", headers=BOB)).status_code == 404
    assert (await client.get(asset["content_url"], headers=BOB)).status_code == 404


async def test_supabase_upload_read_rollback_and_isolation(client: httpx.AsyncClient, storage: FakeStorage,
                                                           monkeypatch: pytest.MonkeyPatch) -> None:
    project = await make_project(client)
    response = await upload(client, project["id"])
    assert response.status_code == 201, response.text
    asset = response.json()
    (key, owner), = (await rows())[0]
    assert key == f"{owner}/{asset['id']}" and (await rows())[1] == 0  # no bytes in the database
    sent = storage.requests[-1]
    assert (sent.method, sent.url.path) == ("POST", f"/storage/v1/object/assets/{key}")
    assert sent.headers["content-type"] == "image/png" and storage.objects[key] == PNG and "photo" not in sent.url.path

    content = await client.get(asset["content_url"])
    assert content.status_code == 200 and content.content == PNG and content.headers["cache-control"] == "private, no-store"
    before = len(storage.requests)
    assert (await client.get(asset["content_url"], headers=BOB)).status_code == 404
    assert (await upload(client, project["id"], headers=BOB)).status_code == 404
    assert len(storage.requests) == before  # ownership is checked before Storage is called

    storage.objects.clear()  # the object is gone but the row is not
    missing = await client.get(asset["content_url"])
    assert missing.status_code == 404 and missing.json()["error"]["code"] == "NOT_FOUND"

    def broken(project: m.Project) -> None:
        raise RuntimeError("the asset transaction failed")

    monkeypatch.setattr("app.services.assets.touch", broken)
    failed = await upload(client, project["id"])
    assert failed.status_code == 500
    upload_request, delete_request = storage.requests[-2:]
    orphan = upload_request.url.path.removeprefix("/storage/v1/object/assets/")
    assert delete_request.method == "DELETE" and json.loads(delete_request.content) == {"prefixes": [orphan]}
    assert storage.objects == {} and len((await rows())[0]) == 1  # rolled back in both places


async def test_supabase_errors_are_bounded_mapped_and_quiet(client: httpx.AsyncClient, storage: FakeStorage,
                                                            caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    project = await make_project(client)

    storage.fail = [500, 503, 502, 500]
    response = await upload(client, project["id"])
    assert response.status_code == 502 and response.json()["error"]["code"] == "PROVIDER_ERROR"
    assert len(storage.requests) == 3 and storage.fail == [500]  # one try and two retries, then stop
    assert PROVIDER_DETAIL not in response.text and (await rows())[0] == []

    storage.fail, storage.requests = [httpx.ConnectError], []
    assert (await upload(client, project["id"])).status_code == 201 and len(storage.requests) == 2  # retried once

    storage.fail, storage.requests = [httpx.ReadTimeout] * 3, []
    timed_out = await upload(client, project["id"])
    assert timed_out.status_code == 504 and timed_out.json()["error"]["code"] == "PROVIDER_TIMEOUT"

    storage.fail, storage.requests = [403], []
    refused = await upload(client, project["id"])
    assert refused.status_code == 502 and len(storage.requests) == 1  # a 4xx is not retried
    assert PROVIDER_DETAIL not in refused.text

    logged = "\n".join(f"{r.getMessage()} {r.__dict__}" for r in caplog.records)
    assert "asset storage" in logged and SECRET not in logged and PROVIDER_DETAIL not in logged


def test_supabase_backend_fails_fast_without_credentials() -> None:
    for url, key in ((None, SECRET), ("https://project.supabase.example", None)):
        with pytest.raises(ValidationError) as caught:
            Settings(_env_file=None, asset_storage_backend="supabase", supabase_url=url, supabase_secret_key=key)
        assert "SUPABASE_URL and SUPABASE_SECRET_KEY" in str(caught.value) and SECRET not in str(caught.value)
    settings = Settings(_env_file=None, asset_storage_backend="supabase", supabase_url="https://project.supabase.example",
                        supabase_secret_key=SECRET)
    assert SECRET not in repr(settings)
    record = logging.LogRecord("t", logging.WARNING, __file__, 1, f"leaked {SECRET}", None, None)
    assert SECRET not in JsonFormatter(_secret_values(settings)).format(record)  # redacted if it ever reaches a log
