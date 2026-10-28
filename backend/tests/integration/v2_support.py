"""Helpers for contract v2 tests (contracts/README.md §13): sample files and a generic run driver."""

from __future__ import annotations

import base64
from typing import Any

import httpx
from pydantic import BaseModel

from tests.integration._support import API, parse, start_run, wait_for_run

PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==")
JPEG = base64.b64decode(
    "/9j/4AAQSkZJRgABAQEASABIAAD/2wBDAP////////////////////////////////////////////////////////////"
    "//////////////////////////wgALCAABAAEBAREA/8QAFBABAAAAAAAAAAAAAAAAAAAAAP/aAAgBAQABPxA="
)
WEBP = base64.b64decode("UklGRhoAAABXRUJQVlA4TA0AAAAvAAAAEAcQERGIiP4HAA==")

IMAGES = {"pixel.png": (PNG, "image/png"), "pixel.jpg": (JPEG, "image/jpeg"), "pixel.webp": (WEBP, "image/webp")}
# Content that must be refused whatever the filename or declared type says (README §13 Uploads).
SPOOFS = {
    "gif": b"GIF89a\x01\x00\x01\x00\x80\x00\x00\xff\xff\xff\x00\x00\x00!\xf9\x04\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;",
    "html": b"<html><body><script>alert(document.cookie)</script></body></html>",
    "svg": b'<svg xmlns="http://www.w3.org/2000/svg" onload="alert(1)"><rect width="1" height="1"/></svg>',
    "exe": b"MZ\x90\x00\x03\x00\x00\x00\x04\x00\x00\x00\xff\xff" + b"\x00" * 64,
    "pdf": b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF",
    "text": b"just some text pretending to be an image",
}


async def upload(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    project_id: Any,
    *,
    kind: str,
    filename: str,
    data: bytes,
    content_type: str,
) -> httpx.Response:
    return await client.post(
        f"{API}/projects/{project_id}/assets",
        files={"file": (filename, data, content_type)},
        data={"kind": kind},
        headers=headers,
    )


async def run_resource(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    path: str,
    body: dict[str, Any],
    run_type: str,
    resource: str,
    model: type[BaseModel],
) -> tuple[Any, Any]:
    """Start a v2 run, wait for it, follow Run.result, and validate the resource. Returns (run, resource)."""
    accepted = await start_run(client, headers, path, body, run_type)
    run = await wait_for_run(client, accepted.run_id, headers)
    assert run.status in ("completed", "partial"), f"{run_type} ended {run.status}: {run.error}"
    assert run.result is not None and run.result.resource == resource, f"Run.result {run.result} (expected {resource})"
    assert run.progress is not None and run.progress.stage == "completed"
    return run, parse(model, await client.get(run.result.url, headers=headers))
