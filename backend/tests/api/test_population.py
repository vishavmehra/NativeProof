"""Contract v3: population studies, social simulation, graph views, participant memory, cancel/resume, isolation."""

import asyncio
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import func, select

from app.db import models as m
from app.db.base import utcnow
from app.db.session import session
from app.llm.gateway import LLMError
from app.schemas.common import StepTrace
from app.services import runs as run_engine
from tests.api import fake_population
from tests.api.test_crud import make_campaign, make_project
from tests.api.test_runs import LLM, configure, demo_setup, discovery_body, study_body
from tests.conftest import BOB, wait_for_run

API = "/api/v1"


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> fake_population.FakePopulation:
    return fake_population.install(monkeypatch)


async def until_saved(fake: fake_population.FakePopulation, index: int) -> None:
    """Wait until the batch's checkpoint has committed, so the run is parked outside any database write."""
    async with asyncio.timeout(5):
        while index not in fake.saved:
            await asyncio.sleep(0.01)


async def start_study(client: httpx.AsyncClient, study_id: str, **body: Any) -> dict[str, Any]:
    response = await client.post(f"{API}/studies/{study_id}/population-studies", json={"population_size": 30} | body)
    assert response.status_code == 202, response.text
    return response.json()


async def test_population_study_social_simulation_and_views(client: httpx.AsyncClient, fake: Any) -> None:
    project, campaign, study = await demo_setup(client)
    discovery = await client.post(f"{API}/projects/{project['id']}/discoveries", json=discovery_body(campaign["id"]))
    assert (await wait_for_run(client, discovery.json()["run_id"], timeout=30))["status"] in ("completed", "partial")
    run = await wait_for_run(client, (await start_study(client, study["id"]))["run_id"])
    assert run["status"] == "completed" and run["result"]["resource"] == "population_study"
    result = (await client.get(run["result"]["url"])).json()
    assert result["completed_interviews"] == 30 and result["failed_interviews"] == 0 and result["mode"] == "demo"
    assert fake.concepts == ["outdoor apparel"]  # the discovery's product category is the Qloo concept
    cited = {UUID(e["id"]) for e in result["evidence"] if e["source_workflow"] == "population_evidence"}
    async with session() as s:  # saved with the population (before any interview), once, and linked from the result
        row = await s.get(m.PopulationStudy, UUID(result["id"]))
        assert len(cited) == 1 and row.result["qloo_calls"][0]["workflow"] == "population_evidence"
        count = await s.scalar(select(func.count()).select_from(m.EvidenceRecord).where(m.EvidenceRecord.id.in_(cited)))
        assert count == 1
    assert result["overall"]["denominator"] == 30 and sum(result["overall"]["counts"].values()) == 30
    assert len(result["by_group"]) == 3 and result["next_actions"] == ["Test the headline with real people."]
    assert result["disclosure"]["is_synthetic"] is True and result["disclosure"]["independent_human_sample"] is False
    sid, pid = result["id"], result["population_id"]

    assert (await client.get(f"{API}/studies/{study['id']}/population-studies")).json()["total"] == 1
    interviews = (await client.get(f"{API}/population-studies/{sid}/interviews", params={"group_id": "grp-1", "limit": 100})).json()
    assert interviews["total"] == 10 and all(i["group_id"] == "grp-1" for i in interviews["items"])
    positive = (await client.get(f"{API}/population-studies/{sid}/interviews", params={"reaction": "positive"})).json()
    assert positive["total"] == 6 and all(i["reaction"] == "positive" for i in positive["items"])
    assert (await client.get(f"{API}/projects/{project['id']}/populations")).json()["total"] == 1
    population = (await client.get(f"{API}/populations/{pid}")).json()
    assert population["size"] == 30 and population["group_count"] == 3
    members = (await client.get(f"{API}/populations/{pid}/participants", params={"group_id": "grp-2", "limit": 5})).json()
    assert members["total"] == 10 and len(members["items"]) == 5

    # Reuse the same population: comparison on identical participants.
    again = await wait_for_run(client, (await start_study(client, study["id"], population_id=pid))["run_id"])
    assert fake.batches_run.count(0) == 2 and (await client.get(again["result"]["url"])).json()["population_id"] == pid
    assert (await client.get(f"{API}/projects/{project['id']}/populations")).json()["total"] == 1  # not rebuilt
    comparison = (await client.get(f"{API}/campaigns/{campaign['id']}/population-comparison",
                                   params={"population_id": pid, "population_study_ids": [sid, again["id"]]})).json()
    assert comparison["consistent_population"] is True and comparison["consistent_protocol"] is True
    assert len(comparison["results"]) == 6 and all(e["weight_definition"] for e in comparison["graph"]["edges"])
    graph = comparison["graph"]
    assert {n["kind"] for n in graph["nodes"]} <= {item["kind"] for item in graph["legend"]}

    sim = await client.post(f"{API}/social-simulations", json={"population_study_id": sid, "rounds": 2})
    assert sim.status_code == 202, sim.text
    sim_run = await wait_for_run(client, sim.json()["run_id"])
    assert sim_run["status"] == "completed"
    simulation = (await client.get(sim_run["result"]["url"])).json()
    assert simulation["rounds_completed"] == 2 and [r["round_index"] for r in simulation["rounds"]] == [1, 2]
    assert simulation["influence_paths"] == ["Test influence path."] and len(simulation["group_shifts"]) == 3
    posts = (await client.get(f"{API}/social-simulations/{simulation['id']}/posts", params={"round_index": 2})).json()
    assert posts["total"] == 6 and all(p["round_index"] == 2 for p in posts["items"])
    assert (await client.get(f"{API}/population-studies/{sid}/social-simulations")).json()["total"] == 1

    for url in (f"{API}/populations/{pid}/landscape", f"{API}/population-studies/{sid}/reaction-map",
                f"{API}/social-simulations/{simulation['id']}/diffusion"):
        view = await client.get(url)
        assert view.status_code == 200, (url, view.text)
        nodes = {n["id"] for n in view.json()["nodes"]}
        assert all(n["is_demo"] for n in view.json()["nodes"])
        assert {n["kind"] for n in view.json()["nodes"]} <= {item["kind"] for item in view.json()["legend"]}, url
        assert all(e["source"] in nodes and e["target"] in nodes and e["provenance"] for e in view.json()["edges"])

    participant = interviews["items"][0]["participant_id"]
    detail = (await client.get(f"{API}/population-studies/{sid}/participants/{participant}")).json()
    assert detail["state"]["stance_source"] in {"interview", "social_round"} and detail["memories"]
    assert len(detail["memories"]) <= 50 and detail["memories"][-1]["kind"] == "interview"


async def test_validation_demo_cap_and_isolation(client: httpx.AsyncClient, fake: Any) -> None:
    project, _, study = await demo_setup(client)
    url = f"{API}/studies/{study['id']}/population-studies"
    capped = await client.post(url, json={"population_size": 121})
    assert capped.status_code == 409 and "120" in capped.json()["error"]["message"]
    missing = await client.post(url, json={})
    assert missing.status_code == 422 and missing.json()["error"]["details"][0]["field"] == "population_size"
    assert (await client.post(url, json={"population_size": 19})).status_code == 422
    assert (await client.post(url, json={"population_size": 30, "regions": [
        {"country_code": "FR", "display_name": "France"}]})).status_code == 409
    run = await wait_for_run(client, (await start_study(client, study["id"]))["run_id"])
    sid = run["id"]
    for path in (f"/population-studies/{sid}", f"/population-studies/{sid}/interviews",
                 f"/studies/{study['id']}/population-studies", f"/projects/{project['id']}/populations",
                 f"/population-studies/{sid}/reaction-map", f"/runs/{sid}"):
        assert (await client.get(f"{API}{path}", headers=BOB)).status_code == 404, path
    assert (await client.post(f"{API}/runs/{sid}/cancel", headers=BOB)).status_code == 404
    assert (await client.post(f"{API}/social-simulations", json={"population_study_id": sid}, headers=BOB)).status_code == 404
    other = await client.post(f"{API}/social-simulations", json={"population_study_id": project["id"]})
    assert other.status_code == 404
    assert (await client.post(f"{API}/runs/{sid}/cancel")).status_code == 409  # already finished


async def test_live_work_limit_and_provider_check(client: httpx.AsyncClient, fake: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    project = await make_project(client)
    campaign = await make_campaign(client, project["id"])
    study = (await client.post(f"{API}/projects/{project['id']}/studies", json=study_body(campaign["id"]))).json()
    url = f"{API}/studies/{study['id']}/population-studies"
    configure(monkeypatch, POPULATION_MAX_PARTICIPANTS="50")
    too_large = await client.post(url, json={"population_size": 51})
    assert too_large.status_code == 422 and "at most 50" in too_large.json()["error"]["message"]  # refused, not reduced
    assert (await client.post(url, json={"population_size": 50})).status_code == 503  # live, no LLM configured
    assert (await client.get(f"{API}/projects/{project['id']}/runs")).json()["total"] == 0
    configure(monkeypatch, **LLM)
    run = await wait_for_run(client, (await start_study(client, study["id"], population_size=50))["run_id"])
    assert run["status"] == "completed" and run["mode"] == "live"


async def test_cancel_keeps_saved_batches_and_resume_finishes(client: httpx.AsyncClient, fake: Any) -> None:
    _, _, study = await demo_setup(client)
    fake.block_after_batch = 0
    accepted = await start_study(client, study["id"])
    run_id = accepted["run_id"]
    await until_saved(fake, 0)
    cancelled = await client.post(f"{API}/runs/{run_id}/cancel")
    assert cancelled.status_code == 200 and cancelled.json()["status"] == "running"  # stops at the next checkpoint
    fake.block_after_batch = None
    fake.release.set()
    run = await wait_for_run(client, run_id)
    assert run["status"] == "cancelled" and run["result"]["resource"] == "population_study"
    saved = (await client.get(run["result"]["url"])).json()
    assert saved["status"] == "cancelled" and saved["completed_interviews"] == 20  # batches 0 and 1 were saved
    resume = await client.post(f"{API}/runs/{run_id}/resume")
    assert resume.status_code == 409  # cancelled is a decision, not an interruption

    fake.fail_after_batch = 0
    failed = await wait_for_run(client, (await start_study(client, study["id"]))["run_id"])
    assert failed["status"] == "failed" and failed["error"]["code"] == "INTERNAL_ERROR"
    assert "Completed work is saved" in failed["error"]["message"] and failed["result"]["resource"] == "population_study"
    resumed = await client.post(f"{API}/runs/{failed['id']}/resume")
    assert resumed.status_code == 202 and resumed.json()["status"] == "queued"
    done = await wait_for_run(client, failed["id"])
    assert done["status"] == "completed"
    final = (await client.get(done["result"]["url"])).json()
    assert final["completed_interviews"] == 30
    batches = [b for b in fake.batches_run[-3:]]
    assert 0 not in batches[1:]  # batch 0 was not redone after resume


async def test_restart_marks_checkpointed_runs_resumable(client: httpx.AsyncClient, fake: Any) -> None:
    _, _, study = await demo_setup(client)
    fake.block_after_batch = 0
    run_id = (await start_study(client, study["id"]))["run_id"]
    await until_saved(fake, 0)
    await run_engine.shutdown()  # a graceful restart (SIGTERM): the task is cancelled and the run made resumable
    graceful = (await client.get(f"{API}/runs/{run_id}")).json()
    assert graceful["status"] == "failed" and graceful["error"]["code"] == "RUN_INTERRUPTED"
    assert "resume" in graceful["error"]["message"] and graceful["result"]["resource"] == "population_study"
    async with session() as s, s.begin():  # a hard kill skips that bookkeeping; simulate it
        run = await s.get(m.AgentRun, UUID(run_id))
        run.status, run.error, run.completed_at = "running", None, None
    assert await run_engine.mark_interrupted_runs() == 1
    run = (await client.get(f"{API}/runs/{run_id}")).json()
    assert run["status"] == "failed" and run["error"]["code"] == "RUN_INTERRUPTED" and run["error"]["retryable"]
    assert "resume" in run["error"]["message"] and run["result"]["resource"] == "population_study"
    fake.block_after_batch = None
    assert (await client.post(f"{API}/runs/{run_id}/resume")).status_code == 202
    assert (await wait_for_run(client, run_id))["status"] == "completed"
    async with session() as s:
        row = await s.get(m.PopulationStudy, UUID(run_id))
        assert row.checkpoint["completed_batches"] == [0, 1, 2]


async def test_resume_needs_a_checkpoint(client: httpx.AsyncClient, fake: Any) -> None:
    project, _, study = await demo_setup(client)
    run = await wait_for_run(client, (await start_study(client, study["id"]))["run_id"])
    async with session() as s, s.begin():
        s.add(m.AgentRun(id=UUID(int=7), project_id=UUID(project["id"]), run_type="market_discovery", status="failed",
                         mode="demo", inputs={}, steps=[], created_at=utcnow()))
    assert (await client.post(f"{API}/runs/{UUID(int=7)}/resume")).status_code == 409  # not a v3 run
    assert (await client.post(f"{API}/runs/{run['id']}/resume")).status_code == 409  # completed
    assert (await client.post(f"{API}/runs/{run['id']}/resume", headers=BOB)).status_code == 404


async def test_follow_ups_and_group_questions(client: httpx.AsyncClient, fake: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    import app.workflows as workflows

    project, _, study = await demo_setup(client)
    sid = (await wait_for_run(client, (await start_study(client, study["id"]))["run_id"]))["id"]
    first = (await client.get(f"{API}/population-studies/{sid}/interviews")).json()["items"][0]
    participant = first["participant_id"]
    ask, group = f"{API}/population-studies/{sid}/participants/{participant}/questions", f"{API}/population-studies/{sid}/groups"
    monkeypatch.delattr(workflows, "answer_followup", raising=False)
    monkeypatch.delattr(workflows, "answer_group_question", raising=False)
    unavailable = await client.post(ask, json={"question": "Why?"})
    assert unavailable.status_code == 501 and unavailable.json()["error"]["code"] == "UNSUPPORTED_CAPABILITY"
    assert (await client.post(ask, json={"question": "Why?"}, headers=BOB)).status_code == 404  # ownership first
    assert (await client.post(f"{group}/grp-1/questions", json={"question": "Q?"}, headers=BOB)).status_code == 404

    async def timeout(**_: Any) -> Any:
        raise LLMError("PROVIDER_TIMEOUT", "The model provider timed out. Try again.", retryable=True,
                       trace=StepTrace(stage="follow_up", agent="test", status="failed", provider="fixture"))

    monkeypatch.setattr(workflows, "answer_followup", timeout, raising=False)
    timed_out = await client.post(ask, json={"question": "Why?"})
    assert timed_out.status_code == 504 and timed_out.json()["error"]["code"] == "PROVIDER_TIMEOUT"
    assert (await client.get(ask)).json()["total"] == 0  # nothing stored

    seen: dict[str, Any] = {}

    async def answer_followup(*, population_study_id: UUID, participant: Any, question: str, mode: str) -> Any:
        seen["memories"] = participant.memories
        return SimpleNamespace(answer="Because of the price.", stance="mixed", model_id="fixture",
                               memory_refs=[participant.memories[0].ref_id, uuid4()])  # one invented ref

    async def answer_group_question(*, population_study_id: UUID, group_id: str, participants: list[Any], question: str,
                                    mode: str) -> Any:
        answers = [SimpleNamespace(participant_id=p.id, answer=f"Answer {p.ordinal}.", stance="positive", memory_refs=[],
                                   model_id="fixture") for p in participants]
        stray = SimpleNamespace(participant_id=uuid4(), answer="Not sampled.", stance="negative", memory_refs=[], model_id=None)
        return SimpleNamespace(answers=[*answers, stray], summary="Mostly positive (interpretation).")

    monkeypatch.setattr(workflows, "answer_followup", answer_followup, raising=False)
    monkeypatch.setattr(workflows, "answer_group_question", answer_group_question, raising=False)
    asked = await client.post(ask, json={"question": "Why?"})
    assert asked.status_code == 201, asked.text
    body = asked.json()
    assert body["is_synthetic"] is True and body["stance"] == "mixed" and body["group_id"] == first["group_id"]
    assert body["memory_refs"] == [str(seen["memories"][0].ref_id)]  # the invented ref is dropped
    assert (await client.get(ask)).json()["total"] == 1
    detail = (await client.get(f"{API}/population-studies/{sid}/participants/{participant}")).json()
    assert detail["memories"][0]["kind"] == "follow_up"  # the answer becomes a memory
    assert (await client.post(ask, json={"question": ""})).status_code == 422

    for size in (2, 11):
        assert (await client.post(f"{group}/grp-2/questions", json={"question": "Q?", "sample_size": size})).status_code == 422
    assert (await client.post(f"{group}/grp-9/questions", json={"question": "Q?"})).status_code == 404
    result = await client.post(f"{group}/grp-2/questions", json={"question": "Would you share it?", "sample_size": 4})
    assert result.status_code == 201, result.text
    data = result.json()
    assert len(data["answers"]) == 4 and {a["group_id"] for a in data["answers"]} == {"grp-2"}  # stray answer dropped
    assert data["stance"]["denominator"] == 4 and "4 of the group's 10" in data["sample_note"]
    again = (await client.post(f"{group}/grp-2/questions", json={"question": "Would you share it?", "sample_size": 4})).json()
    assert {a["participant_id"] for a in again["answers"]} == {a["participant_id"] for a in data["answers"]}  # seeded
    listed = (await client.get(f"{group}/grp-2/questions")).json()
    assert listed["total"] == 2 and len(listed["items"][0]["answers"]) == 4

    for method, url in (("GET", ask), ("POST", ask), ("GET", f"{group}/grp-2/questions"), ("POST", f"{group}/grp-2/questions"),
                        ("GET", f"{API}/population-studies/{sid}/participants/{participant}")):
        response = await client.request(method, url, json={"question": "Q?"} if method == "POST" else None, headers=BOB)
        assert response.status_code == 404, (method, url)
    assert (await client.get(f"{API}/population-studies/{sid}/participants/{project['id']}")).status_code == 404
