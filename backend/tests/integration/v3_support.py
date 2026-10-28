"""Helpers for contract v3 tests (contracts/README.md §14): population studies, social simulation, graph views."""

from __future__ import annotations

import inspect
import re
from collections import Counter
from collections.abc import Callable, Iterable
from typing import Any

import httpx
import pytest

from app.api.routes import populations, runs
from app.schemas.population import GraphView, ReactionDistribution
from tests.integration._support import API, parse, start_run, wait_for_run

# Traits are synthetic variation knobs only; nothing demographic or sensitive may appear on a participant (§14.3).
SENSITIVE = re.compile(
    r"\b(aged?|\d{1,2}\s*(?:years?|yrs?)\s*old|male|female|gender|men|women|ethnic\w*|race|religio\w*|christian|"
    r"muslim|buddhist|hindu|jewish|disab\w*|diagnos\w*|income|salary|married|pregnan\w*|sexual\w*|lgbt\w*)\b",
    re.IGNORECASE,
)
CORE_QUESTIONS = ("first_impression", "comprehension", "relevance", "appeal", "confusion", "trust", "concerns", "improvement")
FOLLOW_UPS = {"brief": 0, "standard": 1, "deep": 2}


def stubbed(*handlers: Callable[..., Any]) -> bool:
    """True while any handler is still the contract stub (its body raises NotImplementedError)."""
    return any("raise NotImplementedError" in inspect.getsource(handler) for handler in handlers)


def needs(*handlers: Callable[..., Any]) -> pytest.MarkDecorator:
    """Skip (not xfail) until D implements the handlers; flips to live automatically when the stub is replaced."""
    names = ", ".join(handler.__name__ for handler in handlers)
    return pytest.mark.skipif(stubbed(*handlers), reason=f"awaiting D: {names} (README §14)")


def needs_workflow(*names: str) -> pytest.MarkDecorator:
    """Skip until the `app.workflows` exposes the entry points the run engine calls (README §14)."""
    import importlib

    try:
        package = importlib.import_module("app.workflows")
        missing = [name for name in names if not hasattr(package, name)]
    except ImportError:
        missing = list(names)
    return pytest.mark.skipif(bool(missing), reason=f"awaiting F: app.workflows.{', '.join(missing)}")


ROUTES = populations
RUNS = runs


def check_distribution(dist: ReactionDistribution, where: str) -> None:
    """rates = counts / denominator; failures are excluded from the denominator and reported (§14.4)."""
    assert sum(dist.counts.values()) == dist.denominator, f"{where}: counts {dict(dist.counts)} != denominator {dist.denominator}"
    assert set(dist.rates) <= set(dist.counts) | {k for k, v in dist.rates.items() if v == 0}, f"{where}: rate without a count"
    for category, count in dist.counts.items():
        expected = count / dist.denominator if dist.denominator else 0.0
        assert abs(dist.rates.get(category, 0.0) - expected) <= 0.0006, f"{where}: rate[{category}] != {count}/{dist.denominator}"
    assert dist.failed >= 0


def tally(reactions: Iterable[str | None]) -> Counter[str]:
    return Counter(reaction for reaction in reactions if reaction is not None)


def check_graph(view: GraphView, *, demo: bool, where: str, limit: int | None = None) -> None:
    """§14.7: stable unique ids, provenance on every edge, weight → weight_definition, no dangling edges."""
    node_ids = [node.id for node in view.nodes]
    edge_ids = [edge.id for edge in view.edges]
    assert len(node_ids) == len(set(node_ids)), f"{where}: duplicate node ids"
    assert len(edge_ids) == len(set(edge_ids)), f"{where}: duplicate edge ids"
    nodes = set(node_ids)
    for edge in view.edges:
        assert edge.source in nodes and edge.target in nodes, f"{where}: edge {edge.id} dangles"
        assert edge.provenance.strip(), f"{where}: edge {edge.id} has no provenance"
        if edge.weight is not None:
            assert edge.weight_definition and edge.weight_definition.strip(), f"{where}: edge {edge.id} weight without a definition"
    for node in view.nodes:
        if demo:
            assert node.is_demo, f"{where}: node {node.id} in a demo project must be marked demo"
        for value in node.facts.values():
            assert not (isinstance(value, str) and SENSITIVE.search(value) and node.kind == "participant"), (
                f"{where}: participant node {node.id} carries a demographic fact"
            )
    if limit is not None:
        assert len(view.nodes) <= limit, f"{where}: {len(view.nodes)} nodes above limit {limit}"
    if view.truncated:
        assert view.limitations, f"{where}: a truncated view must say so in its limitations"


async def check_node_resources(client: httpx.AsyncClient, headers: dict[str, str], view: GraphView, where: str) -> None:
    """No node points to a resource that does not exist (API paths are resolved; UI routes are not)."""
    seen: set[str] = set()
    for node in view.nodes:
        if node.resource and node.resource.startswith(API) and node.resource not in seen:
            seen.add(node.resource)
            response = await client.get(node.resource, headers=headers)
            assert response.status_code == 200, f"{where}: node {node.id} points at {node.resource} -> {response.status_code}"


async def run_population_study(
    client: httpx.AsyncClient, headers: dict[str, str], study_id: Any, **body: Any
) -> tuple[Any, Any]:
    """Start a population study, wait for it, and return (run, PopulationStudyResult)."""
    from app.schemas.population import PopulationStudyResult

    payload = {"population_size": 40, "interview_depth": "brief", "seed": 42, **body}
    accepted = await start_run(client, headers, f"{API}/studies/{study_id}/population-studies", payload, "population_study")
    run = await wait_for_run(client, accepted.run_id, headers, timeout=180)
    assert run.status in ("completed", "partial"), f"population study ended {run.status}: {run.error}"
    assert run.result is not None and run.result.resource == "population_study", run.result
    return run, parse(PopulationStudyResult, await client.get(run.result.url, headers=headers))
