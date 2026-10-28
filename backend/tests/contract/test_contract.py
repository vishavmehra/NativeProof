"""Contract guards: the committed OpenAPI document is current, and every fixture matches its schema.

Fixture files are named <SchemaName>.<variant>.json, e.g. Run.failed.json.
"""

import json
from pathlib import Path

import pytest
from pydantic import BaseModel

from app.main import create_app
from app.schemas import (
    adaptations,
    campaigns,
    common,
    discovery,
    evaluations,
    evidence,
    health,
    projects,
    reports,
    runs,
    studies,
)

CONTRACTS = Path(__file__).resolve().parents[3] / "contracts"
MODELS: dict[str, type[BaseModel]] = {
    name: obj
    for module in (adaptations, campaigns, common, discovery, evaluations, evidence, health, projects, reports, runs, studies)
    for name, obj in vars(module).items()
    if isinstance(obj, type) and issubclass(obj, BaseModel)
}
FIXTURES = sorted((CONTRACTS / "fixtures").glob("*.json"))


def test_openapi_is_current() -> None:
    committed = json.loads((CONTRACTS / "openapi.json").read_text(encoding="utf-8"))
    assert committed == create_app().openapi(), "Regenerate: uv run python -m scripts.export_openapi"


def test_fixtures_exist() -> None:
    assert FIXTURES, "Regenerate: uv run python -m scripts.build_contract_fixtures"


@pytest.mark.parametrize("path", FIXTURES, ids=lambda p: p.name)
def test_fixture_matches_schema(path: Path) -> None:
    MODELS[path.name.split(".")[0]].model_validate_json(path.read_bytes())


@pytest.mark.parametrize("path", FIXTURES, ids=lambda p: p.name)
def test_fixture_is_labeled_demo(path: Path) -> None:
    """Fixtures are development examples; none may claim to be live data."""
    text = path.read_text(encoding="utf-8")
    assert '"is_live_data": true' not in text
    assert '"retrieval_mode": "live"' not in text
