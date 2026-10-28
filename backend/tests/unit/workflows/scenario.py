"""The seeded demo scenario (Northstar, Japan) built from contracts/fixtures, plus small test helpers."""

import json
import re
from pathlib import Path
from uuid import uuid4

from app.core.config import Settings
from app.schemas.adaptations import AdaptationCreate
from app.schemas.campaigns import Campaign
from app.schemas.discovery import DiscoveryCreate
from app.schemas.projects import Project
from app.schemas.studies import Study
from app.workflows import (
    AdaptationInput,
    BrandContext,
    DiscoveryInput,
    RehearsalInput,
    WorkflowContext,
    build_workflow_deps,
)

FIXTURES = Path(__file__).resolve().parents[4] / "contracts" / "fixtures"
PROJECT = Project.model_validate_json((FIXTURES / "Project.json").read_bytes())
CAMPAIGN = Campaign.model_validate_json((FIXTURES / "Campaign.json").read_bytes())
STUDY = Study.model_validate_json((FIXTURES / "Study.json").read_bytes())
CONTENT = CAMPAIGN.current_version.content
VERSION_ID = CAMPAIGN.current_version.id
JP = CAMPAIGN.target_markets[0]
BRAND = BrandContext(**PROJECT.brand.model_dump(exclude={"id", "updated_at"}))
TERMS = ["hiking", "minimal design", "great escape"]


def offline_settings() -> Settings:
    """No .env and blank provider keys: these tests can never reach a paid API."""
    return Settings(_env_file=None, nebius_api_key=None, openrouter_api_key=None, qloo_api_key=None)


def demo_deps():
    return build_workflow_deps("demo", offline_settings())


def context(mode: str = "demo") -> WorkflowContext:
    return WorkflowContext(run_id=uuid4(), project_id=PROJECT.id, campaign_id=CAMPAIGN.id, mode=mode, brand=BRAND)


def discovery_input(mode: str = "demo", terms=TERMS) -> DiscoveryInput:
    request = DiscoveryCreate(
        product_category="outdoor lifestyle apparel", market=JP, reference_terms=terms,
        research_question="Which cultural interests could inform this launch?",
    )
    return DiscoveryInput(context=context(mode), request=request, campaign_content=CONTENT)


def rehearsal_input(grounding, *, content=CONTENT, response_count: int | None = None) -> RehearsalInput:
    config = STUDY.simulation_config
    if response_count is not None:
        config = config.model_copy(update={"response_count": response_count})
    return RehearsalInput(context=context(), study=STUDY, content_version_id=VERSION_ID, content=content,
                          simulation_config=config, grounding_evidence=grounding)


def adaptation_input(grounding, summary=None, variant_count: int = 3) -> AdaptationInput:
    return AdaptationInput(
        context=context(), source_content_version_id=VERSION_ID, source_content=CONTENT,
        request=AdaptationCreate(market=JP, variant_count=variant_count), protected_terms=["Northstar"],
        grounding_evidence=grounding, rehearsal_summary=summary,
    )


class Progress:
    def __init__(self):
        self.calls: list[tuple[str, int, int, str]] = []

    async def __call__(self, stage: str, completed_steps: int, total_steps: int, message: str) -> None:
        self.calls.append((stage, completed_steps, total_steps, message))


_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
_VOLATILE = {"created_at", "latency_ms", "retrieved_at"}


def normalized(model) -> str:
    """Model dump with run-specific ids (numbered by first appearance) and timings removed."""

    def strip(value):
        if isinstance(value, dict):
            return {k: strip(v) for k, v in value.items() if k not in _VOLATILE}
        if isinstance(value, list):
            return [strip(v) for v in value]
        return value

    text = json.dumps(strip(model.model_dump(mode="json")), sort_keys=True)
    seen: dict[str, str] = {}
    return _UUID.sub(lambda m: seen.setdefault(m.group(0), f"<id{len(seen)}>"), text)
