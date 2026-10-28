"""Measure real model cost of a population study and one social round (docs/15 §14). Opt-in, small, no database.

Run from backend/:  NATIVEPROOF_LIVE_TESTS=1 uv run python -m scripts.measure_population_cost [participants]

Uses the real gateway from backend/.env and the demo discovery evidence as grounding (no Qloo call). Prints calls,
tokens, and seconds per stage, per interview batch, and per social round. Never prints keys or prompts.
"""

import asyncio
import os
import sys
import time
from uuid import uuid4

from app.core.config import get_settings
from app.llm import gateway as gw
from app.llm.gateway import LLMGateway
from app.workflows import run_discovery
from app.workflows.population import run_population_study
from app.workflows.social import run_social_simulation
from app.workflows.types import PopulationStudyInput, SocialSimulationInput, WorkflowDeps


async def main(size: int) -> None:
    from tests.unit.workflows.scenario import CONTENT, JP, STUDY, VERSION_ID, context, demo_deps, discovery_input

    calls = {"n": 0}
    original = gw.OpenAICompatibleProvider.complete

    async def counting(self, request):
        calls["n"] += 1
        return await original(self, request)

    gw.OpenAICompatibleProvider.complete = counting
    grounding = (await run_discovery(discovery_input(), demo_deps())).evidence
    deps = WorkflowDeps(qloo=demo_deps().qloo, llm=LLMGateway(get_settings()))
    events = []

    async def checkpoint(event):
        events.append(event)

    started = time.perf_counter()
    study = await run_population_study(PopulationStudyInput(
        context=context("live"), population_study_id=uuid4(), study=STUDY, size=size, regions=[JP], seed=42,
        content_version_id=VERSION_ID, content=CONTENT, interview_depth="standard", grounding_evidence=grounding, batch_size=10,
    ), deps, checkpoint=checkpoint)
    study_seconds, study_calls = time.perf_counter() - started, calls["n"]
    built, interviews = events[0], [i for e in events[1:] for i in e.interviews]
    print(f"population study: status={study.status} participants={size} calls={study_calls} seconds={study_seconds:.1f} "
          f"completed={sum(i.status == 'completed' for i in interviews)} failed={sum(i.status == 'failed' for i in interviews)}")
    for s in study.steps:
        u = s.usage
        print(f"  {s.stage:<24} {s.provider} {s.model_id} {s.latency_ms} ms retries={s.retries} "
              f"tokens={u.input_tokens if u else None}/{u.output_tokens if u else None}")
    calls["n"], events[:] = 0, []
    started = time.perf_counter()
    social = await run_social_simulation(SocialSimulationInput(
        context=context("live"), simulation_id=uuid4(), population_study_id=uuid4(), groups=built.population.groups,
        participants=built.participants, interviews=interviews, content=CONTENT, rounds=1, active_share=0.25, feed_size=5, seed=42,
    ), deps, checkpoint=checkpoint)
    print(f"social (1 round, active 25% = {len(events[0].posts) if events else 0} participants): status={social.status} "
          f"calls={calls['n']} seconds={time.perf_counter() - started:.1f}")
    for s in social.steps:
        u = s.usage
        print(f"  {s.stage:<24} {s.provider} {s.model_id} {s.latency_ms} ms tokens={u.input_tokens if u else None}/"
              f"{u.output_tokens if u else None}")
    gw.OpenAICompatibleProvider.complete = original


if __name__ == "__main__":
    if os.environ.get("NATIVEPROOF_LIVE_TESTS") != "1":
        print("Skipped: set NATIVEPROOF_LIVE_TESTS=1 to make real model calls.")
    else:
        asyncio.run(main(min(100, int(sys.argv[1]) if len(sys.argv) > 1 else 40)))
