"""Opt-in live check: a real discovery returns live, attributed Qloo evidence (contracts/README §5, §7).

Runs only with NATIVEPROOF_LIVE_TESTS=1. Credentials come from the environment, falling back to backend/.env
(QLOO_* and NEBIUS_* only); values are never printed. One small discovery: one term, one reference, no related
interests. Data goes to a temporary SQLite database, never to the real Postgres.

    NATIVEPROOF_LIVE_TESTS=1 uv run pytest -q tests/integration/test_live_qloo.py
"""

import os
from pathlib import Path

import pytest
from dotenv import dotenv_values

from app.schemas.discovery import DiscoveryResult
from tests.integration import invariants as inv
from tests.integration._support import API, parse, running_app, start_run, wait_for_run
from tests.integration.journey import JAPAN, create_live_project

LIVE = os.environ.get("NATIVEPROOF_LIVE_TESTS") == "1"
ENV_FILE = Path(__file__).resolve().parents[2] / ".env"
PASS_THROUGH = ("QLOO_", "NEBIUS_")


def live_values() -> dict[str, str]:
    values = {k: v for k, v in (dotenv_values(ENV_FILE) if ENV_FILE.exists() else {}).items() if v}
    values.update({k: v for k, v in os.environ.items() if v})
    return {k: v for k, v in values.items() if k.startswith(PASS_THROUGH)}


pytestmark = pytest.mark.skipif(not LIVE, reason="set NATIVEPROOF_LIVE_TESTS=1 to run live provider tests")


async def test_live_discovery_returns_live_attributed_evidence(
    qa_env: dict[str, str], monkeypatch: pytest.MonkeyPatch, alice: dict[str, str]
) -> None:
    values = live_values()
    if not values.get("QLOO_API_KEY"):
        pytest.skip("QLOO_API_KEY is not configured")
    monkeypatch.delenv("QLOO_BIN", raising=False)  # the hermetic default points at a missing binary
    # Live Qloo resolves in 10-26 s (qloo_live_smoke_report.md); the hermetic 5 s timeouts would fail by design.
    for key, value in {"QLOO_TIMEOUT_SECONDS": "90", "LLM_REQUEST_TIMEOUT_SECONDS": "90", "LLM_MAX_RETRIES": "1"}.items():
        monkeypatch.setenv(key, value)
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    body = {
        "product_category": "outdoor apparel",
        "market": JAPAN,
        "research_question": "Which outdoor interests could inform a launch?",
        "reference_terms": ["hiking"],
        "discovery_options": {"max_references": 1, "include_related_interests": False},
    }
    async with running_app() as app:
        project = await create_live_project(app.client, alice)
        accepted = await start_run(app.client, alice, f"{API}/projects/{project.id}/discoveries", body, "market_discovery")
        run = await wait_for_run(app.client, accepted.run_id, alice, timeout=240)
        assert run.mode == "live" and run.status in ("completed", "partial"), f"live discovery ended {run.status}: {run.error}"
        result = parse(DiscoveryResult, await app.client.get(f"{API}/projects/{project.id}/discoveries/{run.id}", headers=alice))
    for record in result.evidence:
        inv.check_evidence_semantics(record)
        assert record.retrieval_mode != "fixture", "a live run never falls back to fixtures"
    qloo = [e for e in result.evidence if e.evidence_type == "qloo_source"]
    assert qloo, "the live discovery produced no Qloo evidence"
    for record in qloo:
        assert record.retrieval_mode == "live" and record.is_live_data is True, f"{record.id}: {record.retrieval_mode}"
        assert record.source_provider == "qloo" and record.retrieved_at is not None
        assert record.provenance is not None and record.provenance.fixture_origin is None, "live evidence needs provenance"
        assert record.provenance.request_hash or record.provenance.response_hash, "provenance must identify the call"
    assert any(step.provider and "qloo" in step.provider.split(",") for step in result.run_metadata.steps)
