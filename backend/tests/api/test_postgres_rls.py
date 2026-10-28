"""Opt-in RLS check against a real Supabase Postgres. Everything runs in one transaction that is rolled back.

Run: NATIVEPROOF_TEST_POSTGRES_URL=postgresql+asyncpg://... uv run pytest -m postgres
Skipped otherwise; the default suite never touches a real database.
"""

import json
import os
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.db import models as m

URL = os.environ.get("NATIVEPROOF_TEST_POSTGRES_URL")
pytestmark = [pytest.mark.postgres, pytest.mark.skipif(not URL, reason="set NATIVEPROOF_TEST_POSTGRES_URL to run")]


async def _as(s: AsyncSession, role: str, sub: object = None) -> None:
    await s.execute(text("RESET ROLE"))
    await s.execute(text(f"SET LOCAL ROLE {role}"))
    claims = json.dumps({"sub": str(sub), "role": role}) if sub else ""
    await s.execute(text("SELECT set_config('request.jwt.claims', :c, true)"), {"c": claims})


async def _denied(s: AsyncSession, sql: str, params: dict) -> bool:
    await s.execute(text("SAVEPOINT w"))
    try:
        result = await s.execute(text(sql), params)
        await s.execute(text("RELEASE SAVEPOINT w"))
        return result.rowcount == 0  # UPDATE/DELETE of invisible rows touch nothing
    except Exception:
        await s.execute(text("ROLLBACK TO SAVEPOINT w"))
        return True


async def test_rls_isolates_owners_and_blocks_writes() -> None:
    engine = create_async_engine(URL)  # type: ignore[arg-type]
    alice, bob = uuid4(), uuid4()
    async with AsyncSession(engine) as s:
        await s.begin()
        project = m.Project(id=uuid4(), owner_id=alice, name="rls-test", description=None, objective=None, mode="demo",
                            status="active", target_markets=[])
        s.add(project)
        await s.flush()
        s.add(m.Campaign(project_id=project.id, name="c", campaign_type="slogan", objective=None, evaluation_criteria={}))
        s.add(m.QlooCacheEntry(cache_key=uuid4().hex, workflow_name="find_tags", request_hash="h", response_data={},
                               response_hash=None, retrieval_mode="live", retrieved_at=datetime.now(UTC), expires_at=None))
        await s.flush()
        policies = (await s.execute(text("SELECT DISTINCT cmd FROM pg_policies WHERE schemaname = 'public'"))).scalars().all()
        assert policies == ["SELECT"]
        unprotected = (await s.execute(text(
            "SELECT relname FROM pg_class WHERE relnamespace = 'public'::regnamespace AND relkind = 'r' "
            "AND relname <> 'alembic_version' AND NOT relrowsecurity"))).scalars().all()
        assert unprotected == []
        count = "SELECT count(*) FROM {} WHERE {}"

        await _as(s, "authenticated", alice)
        assert (await s.execute(text(count.format("projects", "id = :p")), {"p": project.id})).scalar() == 1
        assert (await s.execute(text(count.format("campaigns", "project_id = :p")), {"p": project.id})).scalar() == 1
        assert (await s.execute(text("SELECT count(*) FROM qloo_cache"))).scalar() == 0
        assert await _denied(s, "INSERT INTO projects (id, owner_id, name, mode, status, target_markets, created_at, "
                                "updated_at) VALUES (gen_random_uuid(), :o, 'x', 'live', 'active', '[]', now(), now())", {"o": alice})
        assert await _denied(s, "UPDATE projects SET name = 'x' WHERE id = :p", {"p": project.id})

        await _as(s, "authenticated", bob)
        assert (await s.execute(text(count.format("projects", "id = :p")), {"p": project.id})).scalar() == 0
        assert (await s.execute(text(count.format("campaigns", "project_id = :p")), {"p": project.id})).scalar() == 0
        assert await _denied(s, "DELETE FROM campaigns WHERE project_id = :p", {"p": project.id})

        await _as(s, "anon")
        assert (await s.execute(text("SELECT count(*) FROM projects"))).scalar() == 0
        await s.rollback()
    await engine.dispose()
