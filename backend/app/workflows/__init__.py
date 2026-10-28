"""AI workflows: one LangGraph StateGraph per run type, four stages each (contracts/README §6).

Workflows are pure (no database access). The run engine (app/services/runs.py) builds the inputs,
passes a progress callback, and persists the returned outcome.
"""

from app.core.config import Settings
from app.llm.gateway import LLMGateway
from app.schemas.common import DataMode
from app.workflows.adaptation import run_adaptation
from app.workflows.arena import run_arena
from app.workflows.discovery import run_discovery
from app.workflows.evaluation import run_evaluation
from app.workflows.followup import answer_followup, answer_group_question
from app.workflows.markets import run_market_comparison
from app.workflows.population import run_population_study
from app.workflows.profile import run_cultural_profile
from app.workflows.rehearsal import run_rehearsal
from app.workflows.risk import run_risk_scan
from app.workflows.social import run_social_simulation
from app.workflows.types import (
    AdaptationInput,
    ArenaInput,
    ArenaOutcome,
    ArenaVariantSpec,
    AssetBlob,
    CulturalProfileInput,
    CulturalProfileOutcome,
    DiscoverySource,
    MarketComparisonInput,
    MarketComparisonOutcome,
    RiskScanInput,
    RiskScanOutcome,
    AdaptationOutcome,
    BrandContext,
    DiscoveryInput,
    DiscoveryOutcome,
    EvaluationInput,
    EvaluationOutcome,
    OutcomeStatus,
    ProgressFn,
    RehearsalInput,
    RehearsalOutcome,
    WorkflowContext,
    WorkflowDeps,
)


def build_workflow_deps(mode: DataMode, settings: Settings, *, qloo_cache=None) -> WorkflowDeps:
    """demo -> fixture Qloo + fixture LLM (no network); live -> the qloo exec service + the Nebius gateway."""
    from app.integrations.qloo import get_qloo_service

    if mode == "demo":  # demo never sends uploads or prompts to a provider: no vision, fixture LLM
        return WorkflowDeps(qloo=get_qloo_service("demo", settings), llm=LLMGateway(settings, fixture=True))
    llm = LLMGateway(settings)
    return WorkflowDeps(qloo=get_qloo_service("live", settings, cache=qloo_cache), llm=llm, vision=llm.capability("vision"))


__all__ = [
    "AdaptationInput",
    "AdaptationOutcome",
    "BrandContext",
    "DiscoveryInput",
    "DiscoveryOutcome",
    "EvaluationInput",
    "EvaluationOutcome",
    "OutcomeStatus",
    "ProgressFn",
    "RehearsalInput",
    "RehearsalOutcome",
    "WorkflowContext",
    "WorkflowDeps",
    "ArenaInput",
    "ArenaOutcome",
    "ArenaVariantSpec",
    "AssetBlob",
    "CulturalProfileInput",
    "CulturalProfileOutcome",
    "DiscoverySource",
    "MarketComparisonInput",
    "MarketComparisonOutcome",
    "RiskScanInput",
    "RiskScanOutcome",
    "build_workflow_deps",
    "run_arena",
    "run_cultural_profile",
    "run_market_comparison",
    "run_risk_scan",
    "run_adaptation",
    "run_discovery",
    "run_evaluation",
    "run_rehearsal",
    "run_population_study",
    "run_social_simulation",
    "answer_followup",
    "answer_group_question",
]
