"""Readers must never block a run's writes: a run reaches a terminal state while many clients poll it."""

import asyncio
import logging
import sys
from typing import Any

import httpx
import pytest

from tests.api import fake_workflows
from tests.api.test_runs import demo_setup, discovery_body, start
from tests.conftest import wait_for_run

API = "/api/v1"


async def test_heavy_polling_does_not_starve_run_writes(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    fake = fake_workflows.install(monkeypatch)
    original = fake.run_discovery

    async def chatty(inp: Any, deps: Any, progress: Any) -> Any:
        for step in range(20):  # many small writes while 40 readers hammer the same database
            await progress("retrieving_affinities", 1, 4, f"Step {step}.")
        return await original(inp, deps, progress)

    monkeypatch.setattr(sys.modules["app.workflows"], "run_discovery", chatty)
    project, _, _ = await demo_setup(client)
    accepted = await start(client, f"{API}/projects/{project['id']}/discoveries", discovery_body())
    stop = asyncio.Event()

    async def poll() -> None:
        while not stop.is_set():
            assert (await client.get(f"{API}/runs/{accepted['run_id']}")).status_code == 200

    caplog.set_level(logging.WARNING, logger="nativeproof.runs")
    pollers = [asyncio.create_task(poll()) for _ in range(40)]
    try:
        run = await wait_for_run(client, accepted["run_id"], timeout=30)
    finally:
        stop.set()
        await asyncio.gather(*pollers)
    assert run["status"] == "completed"
    assert not [r for r in caplog.records if "Progress update skipped" in r.getMessage()]
