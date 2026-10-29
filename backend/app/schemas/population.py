"""Population studies (contract v3, contracts/README.md §14).

An evidence-grounded synthetic population is interviewed about the actual campaign, then optionally exposed to
peers' reactions over a few bounded social rounds. Everything here is simulated: it is never measured opinion, and a
participant count is a generation target, not a human sample size.
"""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field

from app.schemas.common import ApiModel, DataMode, Label, Market, MediumText, Page, RunMetadata
from app.schemas.evidence import EvidenceRecord
from app.schemas.runs import RunStatus

ReactionCategory = Literal["positive", "mixed", "neutral", "negative", "confused"]
Comprehension = Literal["understood", "partial", "misunderstood"]
InterviewDepth = Literal["brief", "standard", "deep"]
SocialAction = Literal["post", "comment", "share", "ignore"]
# Controlled synthetic variation, never demographics or sensitive traits (README §14.3).
TraitKey = Literal["adoption_style", "price_sensitivity", "media_habit", "tone_preference"]
PopulationSize = Annotated[int, Field(ge=20, le=2000, description="Requested participants; never silently reduced.")]


# --- Population -----------------------------------------------------------------------------------------------


class InterestRef(ApiModel):
    ref_id: str = Field(description="Qloo tag/entity id (live) or a fixture id (demo).")
    ref_kind: Literal["tag", "entity"]
    name: str
    weight: float = Field(
        ge=0, le=1, description="Relative emphasis inside this profile, derived from evidence rank. Not prevalence."
    )
    evidence_ids: list[UUID]


class PopulationGroup(ApiModel):
    """A model-constructed archetype grounded in cited evidence (claim_type interpreted)."""

    id: str = Field(description="Stable within the population, e.g. grp-1.")
    label: Label
    description: str
    region: Market
    share: float = Field(ge=0, le=1, description="Share of participants assigned by configuration; not market share.")
    participant_count: int = Field(ge=0)
    interests: list[InterestRef]
    evidence_ids: list[UUID]


class Participant(ApiModel):
    id: UUID
    population_id: UUID
    group_id: str
    ordinal: int = Field(ge=0, description="Stable index; the same seed reproduces the same participant.")
    region: Market
    interests: list[InterestRef]
    traits: dict[TraitKey, str] = Field(description="Seeded synthetic variation knobs (README §14.3).")
    evidence_ids: list[UUID]
    is_synthetic: Literal[True] = True


class PopulationConstruction(ApiModel):
    method: str = Field(description="How groups were built and participants expanded, in plain language.")
    evidence_run_id: UUID | None = Field(description="Discovery run whose evidence grounded the population.")
    grounded: bool = Field(description="False when no cultural evidence was available; groups are then hypotheses.")
    seed: int
    config_version: str
    model_id: str | None
    prompt_version: str | None


class PopulationSummary(ApiModel):
    id: UUID
    project_id: UUID
    study_id: UUID
    size: int
    regions: list[Market]
    group_count: int
    mode: DataMode
    created_at: datetime


class Population(PopulationSummary):
    groups: list[PopulationGroup]
    construction: PopulationConstruction
    limitations: list[str]


class PopulationPage(Page[PopulationSummary]):
    pass


class ParticipantPage(Page[Participant]):
    pass


# --- Population study (run_type population_study) -------------------------------------------------------------


class PopulationStudyCreate(ApiModel):
    """Construct (or reuse) a population and interview every participant about one campaign version."""

    population_id: UUID | None = Field(
        default=None, description="Reuse a population so versions are compared on the same participants."
    )
    population_size: PopulationSize | None = Field(default=None, description="Required when population_id is absent.")
    regions: Annotated[list[Market], Field(max_length=5)] = Field(
        default=[], description="Defaults to the study market. Ignored when population_id is given."
    )
    content_version_id: UUID | None = Field(default=None, description="Defaults to the campaign's current version.")
    discovery_run_id: UUID | None = Field(default=None, description="Evidence snapshot used to ground the groups.")
    asset_id: UUID | None = Field(default=None, description="Creative shown via verified vision observations only.")
    interview_depth: InterviewDepth = "standard"
    seed: int | None = Field(default=42, ge=0)


class InterviewAnswer(ApiModel):
    question_id: str = Field(description="first_impression, comprehension, relevance, appeal, confusion, trust, "
                                         "concerns, improvement, or follow_up_N.")
    question: str
    answer: str


class Interview(ApiModel):
    id: UUID
    run_id: UUID
    participant_id: UUID
    group_id: str
    region: Market
    content_version_id: UUID
    status: Literal["completed", "failed"]
    answers: list[InterviewAnswer]
    reaction: ReactionCategory | None
    comprehension: Comprehension | None
    themes: list[str]
    concerns: list[str]
    misunderstanding: str | None
    model_id: str | None
    evidence_ids: list[UUID]
    is_synthetic: Literal[True] = True


class InterviewPage(Page[Interview]):
    pass


class ReactionDistribution(ApiModel):
    """Deterministic tallies. Rates use `denominator` (completed interviews); failures are reported, not hidden."""

    denominator: int = Field(ge=0)
    failed: int = Field(ge=0)
    counts: dict[ReactionCategory, int]
    rates: dict[ReactionCategory, float]


class ThemeCount(ApiModel):
    label: str
    count: int = Field(ge=0)
    share: float = Field(ge=0, le=1, description="count / completed interviews in scope.")
    example_interview_ids: list[UUID]


class GroupResult(ApiModel):
    group_id: str
    label: str
    region: Market
    distribution: ReactionDistribution
    themes: list[ThemeCount]
    concerns: list[ThemeCount]
    misunderstandings: list[ThemeCount]


class RegionResult(ApiModel):
    region: Market
    distribution: ReactionDistribution


class PopulationStudySummary(ApiModel):
    id: UUID = Field(description="Equals the run id.")
    project_id: UUID
    study_id: UUID
    campaign_id: UUID
    population_id: UUID
    content_version_id: UUID
    status: RunStatus
    mode: DataMode
    requested_participants: int
    completed_interviews: int
    failed_interviews: int
    created_at: datetime


class SimulationDisclosureV3(ApiModel):
    is_synthetic: Literal[True] = True
    independent_human_sample: Literal[False] = False
    shared_model_note: str = Field(description="Responses share one model's biases; agreement is not confirmation.")
    description: str


class PopulationStudyResult(PopulationStudySummary):
    overall: ReactionDistribution
    by_group: list[GroupResult]
    by_region: list[RegionResult]
    themes: list[ThemeCount]
    misunderstandings: list[ThemeCount]
    concerns: list[ThemeCount]
    group_differences: list[str] = Field(description="Model interpretation of the tallies (claim_type interpreted).")
    evidence_gaps: list[str]
    next_actions: list[str]
    disclosure: SimulationDisclosureV3
    evidence: list[EvidenceRecord]
    limitations: list[str]
    run_metadata: RunMetadata


class PopulationStudyPage(Page[PopulationStudySummary]):
    pass


# --- Social simulation (run_type social_simulation) -----------------------------------------------------------


class SocialSimulationCreate(ApiModel):
    """Bounded multi-round peer exposure on a completed population study."""

    population_study_id: UUID
    rounds: int = Field(default=3, ge=1, le=5)
    active_share: float = Field(default=0.2, ge=0.05, le=0.5, description="Share of participants acting per round.")
    feed_size: int = Field(default=5, ge=2, le=10, description="Peer posts each active participant sees.")
    seed: int | None = Field(default=42, ge=0)


class SocialPost(ApiModel):
    id: UUID
    round_index: int = Field(ge=1)
    participant_id: UUID
    group_id: str
    action: SocialAction
    parent_post_id: UUID | None
    text: str | None
    previous_stance: ReactionCategory | None = Field(description="Stance before this round (interview or last round).")
    stance: ReactionCategory
    reason: str | None = Field(
        description="The participant's stated reason for keeping or changing its stance (model interpretation)."
    )
    seen_post_ids: list[UUID] = Field(description="The feed this participant reacted to (provenance of influence).")
    is_synthetic: Literal[True] = True


class SocialPostPage(Page[SocialPost]):
    pass


class SocialRoundSummary(ApiModel):
    round_index: int
    active_participants: int
    actions: dict[SocialAction, int]
    stance: ReactionDistribution = Field(description="Stance of all participants after this round.")
    shifts: int = Field(description="Participants whose stance changed this round.")
    themes: list[ThemeCount]


class NetworkDefinition(ApiModel):
    method: str = Field(description="How peers were linked, e.g. k nearest by shared-interest similarity, seeded.")
    degree: int
    similarity_definition: str


class GroupShift(ApiModel):
    group_id: str
    label: str
    before: ReactionDistribution
    after: ReactionDistribution


class SocialSimulationSummary(ApiModel):
    id: UUID = Field(description="Equals the run id.")
    project_id: UUID
    population_study_id: UUID
    status: RunStatus
    mode: DataMode
    rounds_requested: int
    rounds_completed: int
    created_at: datetime


class SocialSimulationResult(SocialSimulationSummary):
    network: NetworkDefinition
    rounds: list[SocialRoundSummary]
    group_shifts: list[GroupShift]
    emergent_themes: list[ThemeCount]
    influence_paths: list[str] = Field(description="Model interpretation of shifts with cited post ids.")
    disclosure: SimulationDisclosureV3
    limitations: list[str]
    run_metadata: RunMetadata


class SocialSimulationPage(Page[SocialSimulationSummary]):
    pass


# --- Memory, state, and interrogation (README §14.9) ----------------------------------------------------------

MemoryKind = Literal["interview", "seen_post", "own_post", "follow_up"]


class MemoryItem(ApiModel):
    kind: MemoryKind
    ref_id: UUID = Field(description="The stored interview, post, or follow-up this memory comes from.")
    round_index: int | None
    summary: str = Field(description="Quoted or shortened from the stored record; never invented.")
    created_at: datetime


class ParticipantState(ApiModel):
    population_study_id: UUID
    stance: ReactionCategory | None = Field(description="Latest stance: interview reaction, then later social rounds.")
    stance_source: Literal["interview", "social_round", "none"]
    last_round_index: int | None
    interview_id: UUID | None


class ParticipantDetail(Participant):
    state: ParticipantState
    memories: list[MemoryItem] = Field(description="Most recent first, at most 50.")


class FollowUpCreate(ApiModel):
    question: MediumText


class FollowUpAnswer(ApiModel):
    id: UUID
    population_study_id: UUID
    participant_id: UUID
    group_id: str
    question: str
    answer: str
    stance: ReactionCategory | None
    memory_refs: list[UUID] = Field(description="Memories the answer drew on (interview, posts, earlier answers).")
    model_id: str | None
    created_at: datetime
    is_synthetic: Literal[True] = True


class FollowUpPage(Page[FollowUpAnswer]):
    pass


class GroupQuestionCreate(ApiModel):
    question: MediumText
    sample_size: int = Field(default=5, ge=3, le=10, description="Participants sampled from the group (seeded).")


class GroupQuestionResult(ApiModel):
    id: UUID
    population_study_id: UUID
    group_id: str
    question: str
    answers: list[FollowUpAnswer]
    stance: ReactionDistribution = Field(description="Tally over the sampled answers only.")
    summary: str = Field(description="Model interpretation of the sampled answers.")
    sample_note: str = Field(description="How the sample was drawn; a sample is not the whole group.")
    created_at: datetime


class GroupQuestionPage(Page[GroupQuestionResult]):
    pass


# --- Graph views (README §14.6) -------------------------------------------------------------------------------

ViewNodeKind = Literal[
    "audience_group", "region", "interest", "evidence", "campaign_element", "theme", "reaction", "recommendation",
    "campaign_version", "participant", "post",
]
ViewRelation = Literal[
    "similar_to", "shares_evidence", "in_region", "has_interest", "supports", "reacted_to", "mentions", "feels",
    "motivates", "compared_on", "influenced", "replied_to",
]


class ViewNode(ApiModel):
    id: str
    kind: ViewNodeKind
    label: str
    group_id: str | None
    region: str | None
    size: float | None = Field(description="Count-based magnitude (e.g. interviews); null when not meaningful.")
    facts: dict[str, str | float | int | None] = Field(description="Display facts; every number is a stored tally.")
    resource: str | None = Field(description="Feature page or API resource to open, when one exists.")
    resource_id: str | None
    is_synthetic: bool
    is_demo: bool


class ViewEdge(ApiModel):
    id: str
    source: str
    target: str
    relation: ViewRelation
    weight: float | None
    weight_definition: str | None = Field(description="Required whenever weight is set (no unexplained numbers).")
    provenance: str = Field(description="Persisted field or calculation that establishes the edge.")


class LegendItem(ApiModel):
    kind: ViewNodeKind
    label: str
    description: str


class GraphView(ApiModel):
    view: Literal["audience_landscape", "reaction_map", "campaign_comparison", "social_diffusion"]
    nodes: list[ViewNode]
    edges: list[ViewEdge]
    legend: list[LegendItem]
    truncated: bool
    limitations: list[str]
    generated_at: datetime


class VersionGroupResult(ApiModel):
    content_version_id: UUID
    population_study_id: UUID
    group_id: str
    distribution: ReactionDistribution


class CampaignComparison(ApiModel):
    campaign_id: UUID
    population_id: UUID
    studies: list[PopulationStudySummary]
    results: list[VersionGroupResult]
    consistent_population: bool
    consistent_protocol: bool
    variability_note: str = Field(description="Repeated model sampling varies; no significance claim is made.")
    graph: GraphView
    limitations: list[str]
