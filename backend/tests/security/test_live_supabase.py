"""Opt-in regression for real Supabase auth (AUTH_MODE=supabase, ES256 tokens verified through JWKS).

Runs only when these are set in the environment (never read from .env):
  SUPABASE_URL, SUPABASE_PUBLISHABLE_KEY (or NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY), and a cleanup credential:
  SUPABASE_DATABASE_URL (deletes the test's own anonymous users from auth.users) or SUPABASE_SECRET_KEY /
  SUPABASE_SERVICE_ROLE_KEY (admin API).

    uv run pytest -m live_supabase -q tests/security/test_live_supabase.py

Each run signs up two anonymous users, checks auth and isolation against an in-process backend on a temporary
SQLite database (nothing is written to the real Postgres), then signs both users out and deletes them.
Mirrors the lead's manual check of 2026-10-26.
"""

import base64
import json
import os
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import asyncpg
import httpx
import pytest

from app.schemas.projects import Project, ProjectPage
from tests.integration._support import API, expect_error, parse, running_app

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
PUBLISHABLE_KEY = os.environ.get("SUPABASE_PUBLISHABLE_KEY") or os.environ.get("NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY", "")
ADMIN_KEY = os.environ.get("SUPABASE_SECRET_KEY") or os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
DATABASE_URL = os.environ.get("SUPABASE_DATABASE_URL", "").replace("postgresql+asyncpg://", "postgresql://")

pytestmark = [
    pytest.mark.live_supabase,
    pytest.mark.skipif(
        not (SUPABASE_URL and PUBLISHABLE_KEY and (ADMIN_KEY or DATABASE_URL)),
        reason="set SUPABASE_URL, SUPABASE_PUBLISHABLE_KEY, and SUPABASE_DATABASE_URL or SUPABASE_SECRET_KEY to run",
    ),
]


async def anonymous_user(client: httpx.AsyncClient) -> tuple[str, str]:
    """(user_id, access_token) for a new anonymous user."""
    response = await client.post(
        f"{SUPABASE_URL}/auth/v1/signup",
        headers={"apikey": PUBLISHABLE_KEY, "Content-Type": "application/json"},
        json={"data": {}},
    )
    assert response.status_code == 200, f"anonymous sign-up failed: HTTP {response.status_code}"
    body = response.json()
    assert body.get("access_token") and body.get("user", {}).get("id"), "sign-up returned no session"
    assert body["user"].get("is_anonymous") is True, "expected an anonymous user"
    return body["user"]["id"], body["access_token"]


async def cleanup(client: httpx.AsyncClient, users: list[tuple[str, str]]) -> None:
    """Sign out, then delete only the anonymous users this test created."""
    for _, token in users:
        await client.post(f"{SUPABASE_URL}/auth/v1/logout", headers={"apikey": PUBLISHABLE_KEY, "Authorization": f"Bearer {token}"})
    ids = [user_id for user_id, _ in users]
    if not ids:
        return
    if ADMIN_KEY:
        for user_id in ids:
            response = await client.delete(
                f"{SUPABASE_URL}/auth/v1/admin/users/{user_id}", headers={"apikey": ADMIN_KEY, "Authorization": f"Bearer {ADMIN_KEY}"}
            )
            assert response.status_code in (200, 204, 404), f"admin delete failed: HTTP {response.status_code}"
        return
    url = urlsplit(DATABASE_URL)  # SQLAlchemy-style `?ssl=require` is not an asyncpg DSN parameter
    query = urlencode([(k, v) for k, v in parse_qsl(url.query) if k not in ("ssl", "sslmode")])
    dsn = urlunsplit(url._replace(query=query))
    connection = await asyncpg.connect(dsn, ssl="require", statement_cache_size=0, timeout=20)
    try:
        await connection.execute("DELETE FROM auth.users WHERE id = ANY($1::uuid[]) AND is_anonymous", ids)
        remaining = await connection.fetchval("SELECT count(*) FROM auth.users WHERE id = ANY($1::uuid[])", ids)
    finally:
        await connection.close()
    assert remaining == 0, "the test's anonymous users were not deleted"


def forge(token: str) -> str:
    """Same header and signature, different subject: the signature no longer matches."""
    header, payload, signature = token.split(".")
    claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    claims["sub"] = "00000000-0000-4000-8000-000000000000"
    forged = base64.urlsafe_b64encode(json.dumps(claims).encode()).rstrip(b"=").decode()
    return f"{header}.{forged}.{signature}"


def unsigned(token: str) -> str:
    header = base64.urlsafe_b64encode(b'{"alg":"none","typ":"JWT"}').rstrip(b"=").decode()
    return f"{header}.{token.split('.')[1]}."


async def test_supabase_tokens_and_isolation(qa_env: dict[str, str], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUTH_MODE", "supabase")
    monkeypatch.setenv("SUPABASE_URL", SUPABASE_URL)
    users: list[tuple[str, str]] = []
    async with httpx.AsyncClient(timeout=20) as supabase:
        try:
            users.append(await anonymous_user(supabase))
            users.append(await anonymous_user(supabase))
            (_, token_a), (_, token_b) = users
            a, b = {"Authorization": f"Bearer {token_a}"}, {"Authorization": f"Bearer {token_b}"}
            async with running_app() as app:
                client = app.client
                expect_error(await client.get(f"{API}/projects"), 401, "UNAUTHENTICATED")
                for bad in (forge(token_a), unsigned(token_a), "dev-qa-alice"):
                    expect_error(await client.get(f"{API}/projects", headers={"Authorization": f"Bearer {bad}"}), 401, "UNAUTHENTICATED")
                project = parse(Project, await client.post(f"{API}/projects/demo", headers=a), 201)
                assert project.mode == "demo"
                assert parse(ProjectPage, await client.get(f"{API}/projects", headers=a)).total == 1
                expect_error(await client.get(f"{API}/projects/{project.id}", headers=b), 404, "NOT_FOUND")
                assert parse(ProjectPage, await client.get(f"{API}/projects", headers=b)).total == 0
                assert parse(Project, await client.get(f"{API}/projects/{project.id}", headers=a)).id == project.id
        finally:
            await cleanup(supabase, users)
