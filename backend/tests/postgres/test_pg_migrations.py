"""The full Alembic sequence on a clean PostgreSQL 17 database, and existing-data safety across the latest step.

Alembic is the only migration system. Opt-in: marker `postgres`, skipped unless TEST_POSTGRES_URL is set.
"""

import json
import uuid
from datetime import UTC, datetime
from typing import Any

import asyncpg
import pytest

from tests.postgres._pg import ADMIN_URL, alembic, head_and_previous, plain

pytestmark = [pytest.mark.postgres, pytest.mark.skipif(not ADMIN_URL, reason="set TEST_POSTGRES_URL (disposable server)")]
SEEDED = ("projects", "brand_kits", "campaigns", "campaign_versions", "agent_runs", "evidence_records")


async def public_tables(url: str) -> set[str]:
    connection = await asyncpg.connect(plain(url))
    try:
        rows = await connection.fetch("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
        return {row["tablename"] for row in rows}
    finally:
        await connection.close()


async def test_upgrade_downgrade_upgrade_on_a_fresh_database(fresh_db: str) -> None:
    alembic(fresh_db, "upgrade", "head")
    first = await public_tables(fresh_db)
    assert {"projects", "campaigns", "agent_runs", "evidence_records"} <= first
    alembic(fresh_db, "check", None)  # models and the Postgres schema agree after the full sequence
    alembic(fresh_db, "downgrade", "base")
    assert await public_tables(fresh_db) <= {"alembic_version"}, "downgrade base left tables behind"
    alembic(fresh_db, "upgrade", "head")
    assert await public_tables(fresh_db) == first, "a second upgrade produced a different schema"


async def seed(url: str) -> dict[str, list[dict[str, Any]]]:
    """Rows a real deployment would hold at the previous revision; returns them as stored."""
    now = datetime.now(UTC)
    owner, project, campaign, version, run, evidence, brand = (uuid.uuid4() for _ in range(7))
    market = json.dumps([{"country_code": "JP", "display_name": "Japan"}])
    statements = [
        ("INSERT INTO projects (id, owner_id, name, mode, status, target_markets, created_at, updated_at) "
         "VALUES ($1, $2, 'Seeded', 'live', 'active', $3::jsonb, $4, $4)", (project, owner, market, now)),
        ("INSERT INTO brand_kits (id, project_id, name, voice, preferred_terms, prohibited_terms, protected_terms, "
         "created_at, updated_at) VALUES ($1, $2, 'Trailhead', '[\"calm\"]', '[]', '[\"cheap\"]', '[\"Trailhead\"]', $3, $3)",
         (brand, project, now)),
        ("INSERT INTO campaigns (id, project_id, name, campaign_type, target_markets, evaluation_criteria, created_at, "
         "updated_at) VALUES ($1, $2, 'Spring', 'advertisement', $3::jsonb, $4::jsonb, $5, $5)",
         (campaign, project, market,
          json.dumps({"clarity": 0.3, "brand_fidelity": 0.25, "cultural_relevance": 0.3, "cultural_risk": 0.15}), now)),
        ("INSERT INTO campaign_versions (id, campaign_id, project_id, version_number, content, created_at) "
         "VALUES ($1, $2, $3, 1, $4::jsonb, $5)",
         (version, campaign, project, json.dumps({"headline": "Trails worth the early start"}), now)),
        ("INSERT INTO agent_runs (id, project_id, campaign_id, run_type, status, mode, inputs, steps, created_at) "
         "VALUES ($1, $2, $3, 'market_discovery', 'completed', 'live', '{}', '[]', $4)", (run, project, campaign, now)),
        ("INSERT INTO evidence_records (id, project_id, source_run_id, evidence_type, claim_type, title, summary, "
         "source_provider, attributes, method, retrieval_mode, is_live_data, limitations, created_at) VALUES "
         "($1, $2, $3, 'qloo_source', 'observed', 'Resolved tag', 'Seeded.', 'qloo', '[]', 'provider_result', 'live', "
         "true, '[]', $4)", (evidence, project, run, now)),
    ]
    connection = await asyncpg.connect(plain(url))
    try:
        async with connection.transaction():
            for sql, args in statements:
                await connection.execute(sql, *args)
        return {table: [dict(r) for r in await connection.fetch(f"SELECT * FROM {table} ORDER BY id")] for table in SEEDED}
    finally:
        await connection.close()


async def rows(url: str) -> dict[str, list[dict[str, Any]]]:
    connection = await asyncpg.connect(plain(url))
    try:
        return {table: [dict(r) for r in await connection.fetch(f"SELECT * FROM {table} ORDER BY id")] for table in SEEDED}
    finally:
        await connection.close()


def assert_intact(before: dict[str, list[dict[str, Any]]], after: dict[str, list[dict[str, Any]]], where: str) -> None:
    for table, old_rows in before.items():
        new_rows = after[table]
        assert len(new_rows) == len(old_rows), f"{where}: {table} row count changed"
        for old, new in zip(old_rows, new_rows, strict=True):
            for column, value in old.items():
                assert new.get(column) == value, f"{where}: {table}.{column} changed"


SEED_REVISION = "0004"  # the schema the lead's spec seeds at: v1 + v2 data before population studies


async def test_existing_rows_survive_the_latest_migration(fresh_db: str) -> None:
    head, previous = head_and_previous()
    alembic(fresh_db, "upgrade", SEED_REVISION)
    before = await seed(fresh_db)
    alembic(fresh_db, "upgrade", head)
    after = await rows(fresh_db)
    assert_intact(before, after, f"{SEED_REVISION}->{head}")
    for run in after["agent_runs"]:
        assert run.get("cancel_requested_at") is None, "a new run column must default to NULL for existing runs"
    alembic(fresh_db, "downgrade", previous)
    assert_intact(before, await rows(fresh_db), f"{head}->{previous}")
    alembic(fresh_db, "upgrade", head)
    assert_intact(before, await rows(fresh_db), f"{previous}->{head} again")
