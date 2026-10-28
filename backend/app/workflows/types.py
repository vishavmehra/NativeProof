"""Workflow inputs and outcomes: the interface between the run engine (app/services/runs.py) and the
AI workflows. Workflows are pure (no DB access); the engine persists what they return."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal, Protocol
from uuid import UUID

from pydantic import BaseModel

from app.integrations.qloo.service import QlooCall
from app.schemas.adaptations import Adaptation, AdaptationCreate
from app.schemas.arena import ArenaVariantResult, Improvement, VariantSource
from app.schemas.assets import VisionStatus, VisualObservation
from app.schemas.campaigns import CampaignContent, EvaluationCriteria
from app.schemas.common import DataMode, Market, StepTrace
from app.schemas.discovery import CulturalReference, DiscoveryCreate, MarketBrief
from app.schemas.evaluations import CandidateResult, Comparability, Recommendation, ScoringDefinition
from app.schemas.evidence import EvidenceRecord
from app.schemas.markets import MarketColumn, MarketComparability, MarketComparisonCreate
from app.schemas.profiles import CulturalProfileCreate, ProfileItem
from app.schemas.population import (
    Interview,
    InterviewDepth,
    NetworkDefinition,
    Participant,
    Population,
    PopulationGroup,
    ReactionCategory,
    SocialPost,
)
from app.schemas.projects import BrandExample
from app.schemas.risk import RiskFinding, ScanSource
from app.schemas.runs import RunError
from app.schemas.studies import (
    DimensionResults,
    RehearsalSummary,
    SegmentSummary,
    SimulationConfig,
    SimulationDisclosure,
    Study,
    SyntheticReaction,
)

if TYPE_CHECKING:
    from app.integrations.qloo import QlooService
    from app.llm import LLMGateway

OutcomeStatus = Literal["completed", "partial", "failed"]


class BrandContext(BaseModel):
    """Brand Memory as read by a run. Workflows never write it (D-036)."""

    name: str
    description: str | None = None
    positioning: str | None = None
    voice: list[str] = []
    communication_style: str | None = None
    target_audience: str | None = None
    audience_preferences: str | None = None
    preferred_terms: list[str] = []
    prohibited_terms: list[str] = []
    protected_terms: list[str] = []
    approved_examples: list[BrandExample] = []
    constraints: list[str] = []


class WorkflowContext(BaseModel):
    run_id: UUID
    project_id: UUID
    campaign_id: UUID | None = None
    mode: DataMode
    brand: BrandContext


class ProgressFn(Protocol):
    async def __call__(self, stage: str, completed_steps: int, total_steps: int, message: str) -> None: ...


class DiscoveryInput(BaseModel):
    context: WorkflowContext
    request: DiscoveryCreate
    campaign_content: CampaignContent | None = None


class DiscoveryOutcome(BaseModel):
    status: OutcomeStatus
    references: list[CulturalReference]
    market_brief: MarketBrief | None
    evidence: list[EvidenceRecord]
    limitations: list[str]
    steps: list[StepTrace]
    error: RunError | None = None


class RehearsalInput(BaseModel):
    context: WorkflowContext
    study: Study
    content_version_id: UUID
    content: CampaignContent
    simulation_config: SimulationConfig
    grounding_evidence: list[EvidenceRecord] = []


class RehearsalOutcome(BaseModel):
    status: OutcomeStatus
    simulation_disclosure: SimulationDisclosure
    segments: list[SegmentSummary]
    reactions: list[SyntheticReaction]
    dimension_results: DimensionResults
    summary: RehearsalSummary | None
    evidence: list[EvidenceRecord]
    limitations: list[str]
    steps: list[StepTrace]
    error: RunError | None = None


class AdaptationInput(BaseModel):
    context: WorkflowContext
    source_content_version_id: UUID
    source_content: CampaignContent
    request: AdaptationCreate
    protected_terms: list[str] = []
    grounding_evidence: list[EvidenceRecord] = []
    rehearsal_summary: RehearsalSummary | None = None


class AdaptationOutcome(BaseModel):
    status: OutcomeStatus
    adaptations: list[Adaptation]
    evidence: list[EvidenceRecord]
    limitations: list[str]
    steps: list[StepTrace]
    error: RunError | None = None
    brand_rules_applied: list[str] = []


class EvaluationInput(BaseModel):
    context: WorkflowContext
    evaluation_id: UUID
    source_content_version_id: UUID
    source_content: CampaignContent
    candidates: list[Adaptation]
    criteria: EvaluationCriteria
    market: Market
    grounding_evidence: list[EvidenceRecord] = []
    rehearsal_summary: RehearsalSummary | None = None


class EvaluationOutcome(BaseModel):
    status: OutcomeStatus
    results: list[CandidateResult]
    recommendation: Recommendation | None
    comparability: Comparability
    scoring_version: str
    scoring_definition: ScoringDefinition
    evidence: list[EvidenceRecord]
    limitations: list[str]
    steps: list[StepTrace]
    error: RunError | None = None


# --- Contract v2 workflows (contracts/README §13) ---------------------------------------------


class AssetBlob(BaseModel):
    """An uploaded image, loaded by the engine. Sent only to a verified vision model, never to a text model."""

    asset_id: UUID
    media_type: str
    data: bytes


class DiscoverySource(BaseModel):
    """A completed discovery run, as stored (used to ground Cultural DNA)."""

    run_id: UUID
    market: Market
    references: list[CulturalReference]
    market_brief: MarketBrief | None
    evidence: list[EvidenceRecord]


class CulturalProfileInput(BaseModel):
    context: WorkflowContext
    profile_id: UUID
    request: CulturalProfileCreate
    discoveries: list[DiscoverySource] = []
    previous_items: list[ProfileItem] = []  # the based_on_profile_id version, when regenerating


class CulturalProfileOutcome(BaseModel):
    status: OutcomeStatus
    summary: str | None
    items: list[ProfileItem]
    market_context: list[str]
    missing_evidence: list[str]
    evidence: list[EvidenceRecord]  # new records only (model interpretations)
    brand_rules_applied: list[str]
    limitations: list[str]
    steps: list[StepTrace]
    error: RunError | None = None


class MarketComparisonInput(BaseModel):
    context: WorkflowContext
    comparison_id: UUID
    request: MarketComparisonCreate
    campaign_content: CampaignContent | None = None


class MarketComparisonOutcome(BaseModel):
    status: OutcomeStatus
    columns: list[MarketColumn]
    comparability: MarketComparability
    cross_market_summary: str | None
    evidence: list[EvidenceRecord]  # new records across all markets
    brand_rules_applied: list[str]
    limitations: list[str]
    steps: list[StepTrace]
    error: RunError | None = None


class ArenaVariantSpec(BaseModel):
    variant_id: str  # stable id the engine assigns (shown in ranking and preferred_variant_id)
    label: str
    source: VariantSource
    source_id: UUID | None = None
    content: CampaignContent
    asset: AssetBlob | None = None


class ArenaInput(BaseModel):
    context: WorkflowContext
    arena_id: UUID
    study: Study
    variants: list[ArenaVariantSpec]
    criteria: EvaluationCriteria
    responses_per_variant: int = 6
    grounding_evidence: list[EvidenceRecord] = []


class ArenaOutcome(BaseModel):
    status: OutcomeStatus
    variants: list[ArenaVariantResult]
    ranking: list[str]
    segment_differences: list[str]
    tradeoffs: list[str]
    recommended_improvements: list[Improvement]
    simulation_disclosure: SimulationDisclosure
    vision: VisionStatus
    scoring_definition: ScoringDefinition
    evidence: list[EvidenceRecord]
    brand_rules_applied: list[str]
    limitations: list[str]
    steps: list[StepTrace]
    error: RunError | None = None


class RiskScanInput(BaseModel):
    context: WorkflowContext
    scan_id: UUID
    market: Market
    source_kind: ScanSource
    source_id: UUID | None = None
    content: CampaignContent
    assets: list[AssetBlob] = []
    grounding_evidence: list[EvidenceRecord] = []


class RiskScanOutcome(BaseModel):
    status: OutcomeStatus
    findings: list[RiskFinding]  # status "open"; the engine owns status changes afterwards
    visual_observations: list[VisualObservation]
    vision: VisionStatus
    evidence: list[EvidenceRecord]
    brand_rules_applied: list[str]
    limitations: list[str]
    steps: list[StepTrace]
    error: RunError | None = None


class VisionAnalyzer(Protocol):
    """the `app.llm.vision.VisionClient`, reached through `LLMGateway.capability("vision")`.

    `observe` never raises for provider problems: it returns VisionResult(status: VisionStatus,
    observations: list[VisualObservation], trace: StepTrace | None)."""

    def is_configured(self) -> bool: ...

    async def observe(self, asset_id: UUID, image: bytes, content_type: str, *, stage: str, agent: str) -> Any: ...


@dataclass
class WorkflowDeps:
    qloo: QlooService
    llm: LLMGateway
    vision: VisionAnalyzer | None = None  # None: vision is unavailable (never a text model instead)


# --- Contract v3: population studies and social simulation (contracts/README §14) ---------------------------------


class PopulationBuilt(BaseModel):
    """Sent once, before any interview; the engine persists the population, its participants, and `evidence` (the new
    Qloo records the groups cite, so a resumed run never cites records that were not saved). Persist by id: the same
    records are listed again in `PopulationStudyOutcome.evidence`."""

    population: Population
    participants: list[Participant]
    evidence: list[EvidenceRecord] = []


class InterviewBatch(BaseModel):
    """Idempotent by `index` (participants sorted by ordinal, chunked by batch_size)."""

    index: int
    interviews: list[Interview]  # completed and failed interviews of this batch


class SocialRound(BaseModel):
    """Idempotent by `index` (1-based round)."""

    index: int
    posts: list[SocialPost]
    stances: dict[UUID, ReactionCategory]  # every participant's stance after this round


class CheckpointFn(Protocol):
    """Awaited after each event; it may raise the engine's RunCancelled after persisting (the workflow lets it pass)."""

    async def __call__(self, event: PopulationBuilt | InterviewBatch | SocialRound) -> None: ...


class PopulationStudyInput(BaseModel):
    context: WorkflowContext
    population_study_id: UUID  # = run id
    study: Study
    population: Population | None = None  # None: construct it (then PopulationBuilt is sent)
    participants: list[Participant] = []  # present when reusing a population
    size: int
    regions: list[Market]
    seed: int = 42
    content_version_id: UUID
    content: CampaignContent
    asset: AssetBlob | None = None
    interview_depth: InterviewDepth = "standard"
    grounding_evidence: list[EvidenceRecord] = []  # the discovery snapshot (discovery_run_id), cited by id
    evidence_run_id: UUID | None = None
    concept: str | None = None  # short phrase looked up in Qloo, e.g. the discovery run's product category
    batch_size: int = 10
    completed_batches: list[int] = []  # resume: skip these batch indices
    completed_interviews: list[Interview] = []  # resume: stored interviews of completed batches (for the analysis)


class PopulationStudyOutcome(BaseModel):
    """Tallies are not here: the engine computes them from stored interviews with app.analytics.population."""

    status: OutcomeStatus
    group_differences: list[str]
    evidence_gaps: list[str]
    next_actions: list[str]
    evidence: list[EvidenceRecord]  # new records only (also sent with PopulationBuilt; persist by id)
    limitations: list[str]
    steps: list[StepTrace]
    error: RunError | None = None
    qloo_calls: list[QlooCall] = []  # every Qloo request for the evidence, cache hits included (store with the run)


class SocialSimulationInput(BaseModel):
    context: WorkflowContext
    simulation_id: UUID  # = run id
    population_study_id: UUID
    groups: list[PopulationGroup]
    participants: list[Participant]
    interviews: list[Interview]  # the study's interviews: initial stances and round-1 feeds
    content: CampaignContent
    rounds: int = 3
    active_share: float = 0.2
    feed_size: int = 5
    degree: int = 6
    seed: int = 42
    completed_rounds: list[int] = []  # resume: skip these rounds
    prior_posts: list[SocialPost] = []  # resume: stored posts of completed rounds


class FollowUpReply(BaseModel):
    """One synthetic answer (README §14.8); the engine stores it as a FollowUp, which then becomes a memory."""

    participant_id: UUID
    answer: str
    stance: ReactionCategory | None
    memory_refs: list[UUID]  # stored MemoryItem.ref_id values only
    model_id: str | None
    trace: StepTrace | None = None  # None for demo answers (no model call)


class GroupReply(BaseModel):
    """Answers of the sampled participants (the engine samples and tallies) plus a model summary of those answers."""

    answers: list[FollowUpReply]
    summary: str
    trace: StepTrace | None = None


class SocialSimulationOutcome(BaseModel):
    status: OutcomeStatus
    network: NetworkDefinition
    influence_paths: list[str]
    limitations: list[str]
    steps: list[StepTrace]
    error: RunError | None = None

