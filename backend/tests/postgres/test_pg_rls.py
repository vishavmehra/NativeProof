"""Row level security on PostgreSQL 17 with the Supabase stub (D-041: RLS protects the Data API, not the backend).

Every user-owned table has RLS enabled. Acting as `authenticated` with sub=A, user A sees only the rows; user B
sees none of them; `anon` sees nothing; nobody can write through these roles.
"""

import json
import uuid
from datetime import UTC, datetime

import asyncpg
import pytest

from tests.postgres._pg import ADMIN_URL, alembic, plain

pytestmark = [pytest.mark.postgres, pytest.mark.skipif(not ADMIN_URL, reason="set TEST_POSTGRES_URL (disposable server)")]
SEEDED = ("projects", "brand_kits", "campaigns", "agent_runs", "evidence_records")
BACKEND_ONLY = {"qloo_cache", "embeddings"}  # RLS on, no policy: nobody but the owner reads them


async def user_owned_tables(connection: asyncpg.Connection) -> list[str]:
    rows = await connection.fetch(
        "SELECT DISTINCT table_name FROM information_schema.columns WHERE table_schema = 'public' "
        "AND column_name IN ('project_id', 'owner_id') ORDER BY 1"
    )
    return [row["table_name"] for row in rows]


async def seed_user(connection: asyncpg.Connection, owner: uuid.UUID) -> uuid.UUID:
    now, project, campaign, run = datetime.now(UTC), uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    market = json.dumps([{"country_code": "JP", "display_name": "Japan"}])
    await connection.execute(
        "INSERT INTO projects (id, owner_id, name, mode, status, target_markets, created_at, updated_at) "
        "VALUES ($1, $2, 'P', 'demo', 'active', $3::jsonb, $4, $4)", project, owner, market, now)
    await connection.execute(
        "INSERT INTO brand_kits (id, project_id, name, voice, preferred_terms, prohibited_terms, protected_terms, "
        "created_at, updated_at) VALUES ($1, $2, 'B', '[]', '[]', '[]', '[]', $3, $3)", uuid.uuid4(), project, now)
    await connection.execute(
        "INSERT INTO campaigns (id, project_id, name, campaign_type, target_markets, evaluation_criteria, created_at, "
        "updated_at) VALUES ($1, $2, 'C', 'slogan', $3::jsonb, '{}', $4, $4)", campaign, project, market, now)
    await connection.execute(
        "INSERT INTO agent_runs (id, project_id, campaign_id, run_type, status, mode, inputs, steps, created_at) "
        "VALUES ($1, $2, $3, 'market_discovery', 'completed', 'demo', '{}', '[]', $4)", run, project, campaign, now)
    await connection.execute(
        "INSERT INTO evidence_records (id, project_id, source_run_id, evidence_type, claim_type, title, summary, "
        "source_provider, attributes, method, retrieval_mode, is_live_data, limitations, created_at) VALUES "
        "($1, $2, $3, 'qloo_source', 'observed', 'T', 'S', 'fixture', '[]', 'provider_result', 'fixture', false, "
        "'[]', $4)", uuid.uuid4(), project, run, now)
    return project


async def visible(connection: asyncpg.Connection, role: str, sub: uuid.UUID | None) -> dict[str, set[uuid.UUID]]:
    """Project ids visible per seeded table when acting as `role` with JWT subject `sub`."""
    seen: dict[str, set[uuid.UUID]] = {}
    async with connection.transaction():
        await connection.execute(f"SET LOCAL ROLE {role}")
        claims = json.dumps({"sub": str(sub), "role": role}) if sub else ""
        await connection.execute("SELECT set_config('request.jwt.claims', $1, true)", claims)
        for table in SEEDED:
            column = "id" if table == "projects" else "project_id"
            seen[table] = {row[0] for row in await connection.fetch(f"SELECT {column} FROM {table}")}
    return seen


async def test_rls_isolates_users_and_hides_everything_from_anon(fresh_db: str) -> None:
    alembic(fresh_db, "upgrade", "head")
    connection = await asyncpg.connect(plain(fresh_db))
    try:
        tables = await user_owned_tables(connection)
        rls = {row["relname"]: row["relrowsecurity"] for row in await connection.fetch(
            "SELECT relname, relrowsecurity FROM pg_class WHERE relnamespace = 'public'::regnamespace AND relkind = 'r'")}
        missing = [t for t in [*tables, *BACKEND_ONLY] if t in rls and not rls[t]]
        assert not missing, f"RLS disabled on user-owned tables: {missing}"

        user_a, user_b = uuid.uuid4(), uuid.uuid4()
        project_a = await seed_user(connection, user_a)
        project_b = await seed_user(connection, user_b)
        as_a = await visible(connection, "authenticated", user_a)
        as_b = await visible(connection, "authenticated", user_b)
        as_anon = await visible(connection, "anon", None)
        for table in SEEDED:
            assert as_a[table] == {project_a}, f"{table}: user A sees {as_a[table]}"
            assert as_b[table] == {project_b}, f"{table}: user B sees A's rows or none of its own"
            assert as_anon[table] == set(), f"{table}: anon sees rows"
        for table in BACKEND_ONLY & set(rls):
            async with connection.transaction():
                await connection.execute("SET LOCAL ROLE authenticated")
                await connection.execute("SELECT set_config('request.jwt.claims', $1, true)", json.dumps({"sub": str(user_a)}))
                assert await connection.fetchval(f"SELECT count(*) FROM {table}") == 0
        with pytest.raises(asyncpg.PostgresError):  # no write policies: the Data API cannot write
            async with connection.transaction():
                await connection.execute("SET LOCAL ROLE authenticated")
                await connection.execute("SELECT set_config('request.jwt.claims', $1, true)", json.dumps({"sub": str(user_a)}))
                await connection.execute(
                    "INSERT INTO campaigns (id, project_id, name, campaign_type, target_markets, evaluation_criteria, "
                    "created_at, updated_at) VALUES ($1, $2, 'X', 'slogan', '[]', '{}', now(), now())", uuid.uuid4(), project_a)
    finally:
        await connection.close()
