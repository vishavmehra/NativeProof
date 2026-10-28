"""ORM tables (docs/06_DATABASE_SCHEMA.md with decisions D-005..D-008, D-018).

Ownership: `projects.owner_id` is the caller's user id. Every child row carries
`project_id`, and composite foreign keys such as (campaign_id, project_id) ->
campaigns(id, project_id) make cross-project references impossible at the database level.
Nothing cascades: deleting a project archives it (D-011).
"""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, ForeignKey, ForeignKeyConstraint, Index, LargeBinary, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, utcnow

RUN_TYPES = (
    "'market_discovery', 'campaign_rehearsal', 'campaign_adaptation', 'campaign_evaluation', "
    "'cultural_profile', 'campaign_arena', 'risk_scan', 'market_comparison', 'population_study', 'social_simulation'"
)
RUN_STATUSES = "'queued', 'running', 'completed', 'partial', 'failed', 'cancelled'"


def _fk(columns: list[str], table: str, remote: list[str]) -> ForeignKeyConstraint:
    return ForeignKeyConstraint(columns, [f"{table}.{column}" for column in remote])


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    owner_id: Mapped[UUID]
    name: Mapped[str]
    description: Mapped[str | None]
    objective: Mapped[str | None]
    mode: Mapped[str]
    status: Mapped[str] = mapped_column(default="active")
    target_markets: Mapped[list] = mapped_column(default=list)
    last_activity_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow)

    __table_args__ = (
        CheckConstraint("mode IN ('live', 'demo')", name="mode"),
        CheckConstraint("status IN ('active', 'archived')", name="status"),
        Index("ix_projects_owner_id_last_activity_at", "owner_id", "last_activity_at"),
    )


class BrandKit(Base):
    """One brand kit per project in the MVP."""

    __tablename__ = "brand_kits"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id"), unique=True)
    name: Mapped[str]
    description: Mapped[str | None]
    voice: Mapped[list] = mapped_column(default=list)
    target_audience: Mapped[str | None]
    preferred_terms: Mapped[list] = mapped_column(default=list)
    prohibited_terms: Mapped[list] = mapped_column(default=list)
    protected_terms: Mapped[list] = mapped_column(default=list)
    positioning: Mapped[str | None]
    communication_style: Mapped[str | None]
    audience_preferences: Mapped[str | None]
    approved_examples: Mapped[list] = mapped_column(default=list)
    constraints: Mapped[list] = mapped_column(default=list)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow)


class Campaign(Base):
    __tablename__ = "campaigns"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id"))
    name: Mapped[str]
    campaign_type: Mapped[str]
    objective: Mapped[str | None]
    target_markets: Mapped[list] = mapped_column(default=list)
    evaluation_criteria: Mapped[dict]
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow)

    __table_args__ = (
        UniqueConstraint("id", "project_id"),
        Index("ix_campaigns_project_id_updated_at", "project_id", "updated_at"),
    )


class CampaignVersion(Base):
    """Immutable content snapshots (D-006). The current version has the highest number."""

    __tablename__ = "campaign_versions"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    campaign_id: Mapped[UUID]
    project_id: Mapped[UUID]
    version_number: Mapped[int]
    content: Mapped[dict]
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    __table_args__ = (
        _fk(["campaign_id", "project_id"], "campaigns", ["id", "project_id"]),
        UniqueConstraint("campaign_id", "version_number"),
        UniqueConstraint("id", "campaign_id"),
        CheckConstraint("version_number >= 1", name="version_number"),
    )


class Study(Base):
    """A rehearsal configuration (D-005)."""

    __tablename__ = "studies"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID]
    campaign_id: Mapped[UUID]
    name: Mapped[str]
    market: Mapped[dict]
    research_questions: Mapped[list]
    dimensions: Mapped[list]
    segments: Mapped[list] = mapped_column(default=list)
    simulation_config: Mapped[dict]
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow)

    __table_args__ = (
        _fk(["campaign_id", "project_id"], "campaigns", ["id", "project_id"]),
        UniqueConstraint("id", "project_id"),
        Index("ix_studies_project_id_created_at", "project_id", "created_at"),
        Index("ix_studies_campaign_id_created_at", "campaign_id", "created_at"),
    )


class AgentRun(Base):
    """An API run (D-007). Per-stage traces live in `steps` (a StepTrace list), not child rows."""

    __tablename__ = "agent_runs"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id"))
    campaign_id: Mapped[UUID | None]
    study_id: Mapped[UUID | None]
    run_type: Mapped[str]
    status: Mapped[str] = mapped_column(default="queued")
    mode: Mapped[str]
    progress: Mapped[dict | None]
    inputs: Mapped[dict] = mapped_column(default=dict)
    result: Mapped[dict | None]
    result_ref: Mapped[dict | None]
    error: Mapped[dict | None]
    steps: Mapped[list] = mapped_column(default=list)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    started_at: Mapped[datetime | None]
    completed_at: Mapped[datetime | None]
    cancel_requested_at: Mapped[datetime | None]  # cooperative cancel, honored at the next checkpoint (0005)

    __table_args__ = (
        _fk(["campaign_id", "project_id"], "campaigns", ["id", "project_id"]),
        _fk(["study_id", "project_id"], "studies", ["id", "project_id"]),
        UniqueConstraint("id", "project_id"),
        CheckConstraint(f"run_type IN ({RUN_TYPES})", name="run_type"),
        CheckConstraint(f"status IN ({RUN_STATUSES})", name="status"),
        CheckConstraint("mode IN ('live', 'demo')", name="mode"),
        Index("ix_agent_runs_project_id_created_at", "project_id", "created_at"),
        Index("ix_agent_runs_study_id_created_at", "study_id", "created_at"),
        Index("ix_agent_runs_status", "status"),
    )


class EvidenceRecord(Base):
    """Normalized evidence. evidence_type says what produced it; claim_type its epistemic status (D-015)."""

    __tablename__ = "evidence_records"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id"))
    source_run_id: Mapped[UUID | None]
    evidence_type: Mapped[str]
    claim_type: Mapped[str]
    title: Mapped[str]
    summary: Mapped[str]
    source_provider: Mapped[str]
    source_workflow: Mapped[str | None]
    source_reference: Mapped[str | None]
    subject: Mapped[dict | None]
    related_entity: Mapped[dict | None]
    attributes: Mapped[list] = mapped_column(default=list)
    method: Mapped[str]
    retrieval_mode: Mapped[str]
    is_live_data: Mapped[bool]
    retrieved_at: Mapped[datetime | None]
    limitations: Mapped[list] = mapped_column(default=list)
    provenance: Mapped[dict | None]
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    __table_args__ = (
        _fk(["source_run_id", "project_id"], "agent_runs", ["id", "project_id"]),
        CheckConstraint("NOT (is_live_data AND retrieval_mode NOT IN ('live', 'cached'))", name="live_flag"),
        Index("ix_evidence_records_project_id_created_at", "project_id", "created_at"),
        Index("ix_evidence_records_project_id_evidence_type", "project_id", "evidence_type"),
        Index("ix_evidence_records_source_run_id", "source_run_id"),
    )


class SyntheticResponse(Base):
    """One AI-generated reaction (SyntheticReaction in `payload`). Never a real participant."""

    __tablename__ = "synthetic_responses"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID]
    study_id: Mapped[UUID]
    run_id: Mapped[UUID]
    position: Mapped[int]
    segment_label: Mapped[str]
    sentiment: Mapped[str]
    payload: Mapped[dict]
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    __table_args__ = (
        _fk(["study_id", "project_id"], "studies", ["id", "project_id"]),
        _fk(["run_id", "project_id"], "agent_runs", ["id", "project_id"]),
        Index("ix_synthetic_responses_run_id_position", "run_id", "position"),
    )


class Adaptation(Base):
    __tablename__ = "adaptations"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID]
    campaign_id: Mapped[UUID]
    study_id: Mapped[UUID | None]
    run_id: Mapped[UUID | None]
    source_content_version_id: Mapped[UUID]
    parent_adaptation_id: Mapped[UUID | None] = mapped_column(ForeignKey("adaptations.id"))
    position: Mapped[int] = mapped_column(default=0)
    origin: Mapped[str]
    mode: Mapped[str]
    market: Mapped[dict]
    label: Mapped[str]
    strategy: Mapped[str]
    content: Mapped[dict]
    changes: Mapped[list] = mapped_column(default=list)
    checks: Mapped[dict]
    warnings: Mapped[list] = mapped_column(default=list)
    limitations: Mapped[list] = mapped_column(default=list)
    context: Mapped[dict]
    evidence_ids: Mapped[list] = mapped_column(default=list)
    # Protected terms in force when this version was made (brand kit plus request); revisions recheck against them.
    protected_terms: Mapped[list] = mapped_column(default=list)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    __table_args__ = (
        _fk(["campaign_id", "project_id"], "campaigns", ["id", "project_id"]),
        _fk(["source_content_version_id", "campaign_id"], "campaign_versions", ["id", "campaign_id"]),
        _fk(["run_id", "project_id"], "agent_runs", ["id", "project_id"]),
        _fk(["study_id", "project_id"], "studies", ["id", "project_id"]),
        CheckConstraint("origin IN ('generated', 'user_edit')", name="origin"),
        Index("ix_adaptations_campaign_id_created_at", "campaign_id", "created_at"),
        Index("ix_adaptations_run_id", "run_id"),
    )


class Evaluation(Base):
    """One row per comparison; the original is a candidate inside `results` (D-008)."""

    __tablename__ = "evaluations"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID]
    campaign_id: Mapped[UUID]
    study_id: Mapped[UUID | None]
    run_id: Mapped[UUID]
    source_content_version_id: Mapped[UUID]
    status: Mapped[str]
    market: Mapped[dict]
    criteria: Mapped[dict]
    results: Mapped[list] = mapped_column(default=list)
    recommendation: Mapped[dict | None]
    comparability: Mapped[dict]
    scoring_version: Mapped[str]
    scoring_definition: Mapped[dict]
    limitations: Mapped[list] = mapped_column(default=list)
    evidence_ids: Mapped[list] = mapped_column(default=list)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    __table_args__ = (
        _fk(["campaign_id", "project_id"], "campaigns", ["id", "project_id"]),
        _fk(["source_content_version_id", "campaign_id"], "campaign_versions", ["id", "campaign_id"]),
        _fk(["run_id", "project_id"], "agent_runs", ["id", "project_id"]),
        _fk(["study_id", "project_id"], "studies", ["id", "project_id"]),
        Index("ix_evaluations_campaign_id_created_at", "campaign_id", "created_at"),
    )


class Report(Base):
    """A persisted, versioned snapshot (`content` is the full Report)."""

    __tablename__ = "reports"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID]
    campaign_id: Mapped[UUID]
    study_id: Mapped[UUID | None]
    title: Mapped[str]
    status: Mapped[str]
    version_number: Mapped[int]
    mode: Mapped[str]
    content: Mapped[dict]
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    __table_args__ = (
        _fk(["campaign_id", "project_id"], "campaigns", ["id", "project_id"]),
        _fk(["study_id", "project_id"], "studies", ["id", "project_id"]),
        UniqueConstraint("campaign_id", "version_number"),
        CheckConstraint("status IN ('completed', 'partial')", name="status"),
        Index("ix_reports_project_id_created_at", "project_id", "created_at"),
    )


class QlooCacheEntry(Base):
    """Live Qloo results only; fixture results never enter this table (docs/06 section 15)."""

    __tablename__ = "qloo_cache"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    cache_key: Mapped[str] = mapped_column(unique=True)
    workflow_name: Mapped[str]
    request_hash: Mapped[str]
    response_data: Mapped[dict]
    response_hash: Mapped[str | None]
    retrieval_mode: Mapped[str]
    retrieved_at: Mapped[datetime]
    expires_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    __table_args__ = (
        CheckConstraint("retrieval_mode = 'live'", name="retrieval_mode"),
        Index("ix_qloo_cache_expires_at", "expires_at"),
    )


# --- contract v2 (migration 0003) ---------------------------------------------------------
# A generated resource row exists from run start; `result` holds the stored outcome payload
# (with an `evidence_ids` list) once the run finishes. Status is read from the run.


class CulturalProfile(Base):
    __tablename__ = "cultural_profiles"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID]
    campaign_id: Mapped[UUID | None]
    run_id: Mapped[UUID | None]
    lineage_id: Mapped[UUID]
    version: Mapped[int]
    subject: Mapped[str]
    title: Mapped[str]
    markets: Mapped[list]
    notes: Mapped[str | None]
    mode: Mapped[str]
    brand_name: Mapped[str]
    source_discovery_run_ids: Mapped[list] = mapped_column(default=list)
    result: Mapped[dict | None]
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow)

    __table_args__ = (
        _fk(["campaign_id", "project_id"], "campaigns", ["id", "project_id"]),
        _fk(["run_id", "project_id"], "agent_runs", ["id", "project_id"]),
        UniqueConstraint("lineage_id", "version"),
        CheckConstraint("version >= 1", name="version"),
        Index("ix_cultural_profiles_project_id_created_at", "project_id", "created_at"),
    )


class MarketComparison(Base):
    __tablename__ = "market_comparisons"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID]
    campaign_id: Mapped[UUID | None]
    run_id: Mapped[UUID]
    markets: Mapped[list]
    product_category: Mapped[str]
    research_question: Mapped[str]
    reference_terms: Mapped[list] = mapped_column(default=list)
    result: Mapped[dict | None]
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    __table_args__ = (
        _fk(["campaign_id", "project_id"], "campaigns", ["id", "project_id"]),
        _fk(["run_id", "project_id"], "agent_runs", ["id", "project_id"]),
        Index("ix_market_comparisons_project_id_created_at", "project_id", "created_at"),
    )


class Snapshot(Base):
    """A saved pointer to a finished discovery run, whose stored result is immutable."""

    __tablename__ = "snapshots"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID]
    campaign_id: Mapped[UUID | None]
    discovery_run_id: Mapped[UUID]
    label: Mapped[str]
    market: Mapped[dict]
    product_category: Mapped[str]
    reference_terms: Mapped[list] = mapped_column(default=list)
    captured_at: Mapped[datetime]
    mode: Mapped[str]
    reference_count: Mapped[int]
    evidence_count: Mapped[int]
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    __table_args__ = (
        _fk(["discovery_run_id", "project_id"], "agent_runs", ["id", "project_id"]),
        UniqueConstraint("id", "project_id"),
        Index("ix_snapshots_project_id_created_at", "project_id", "created_at"),
    )


class TrendComparison(Base):
    __tablename__ = "trend_comparisons"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID]
    base_snapshot_id: Mapped[UUID]
    target_snapshot_id: Mapped[UUID]
    comparable: Mapped[bool]
    change_count: Mapped[int]
    content: Mapped[dict]
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    __table_args__ = (
        _fk(["base_snapshot_id", "project_id"], "snapshots", ["id", "project_id"]),
        _fk(["target_snapshot_id", "project_id"], "snapshots", ["id", "project_id"]),
        Index("ix_trend_comparisons_project_id_created_at", "project_id", "created_at"),
    )


class Arena(Base):
    __tablename__ = "arenas"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID]
    campaign_id: Mapped[UUID]
    study_id: Mapped[UUID]
    run_id: Mapped[UUID]
    variants: Mapped[list]  # as requested: variant_id, label, source, source_id, asset_id
    criteria: Mapped[dict]
    preferred_variant_id: Mapped[str | None]
    result: Mapped[dict | None]
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow)

    __table_args__ = (
        _fk(["campaign_id", "project_id"], "campaigns", ["id", "project_id"]),
        _fk(["study_id", "project_id"], "studies", ["id", "project_id"]),
        _fk(["run_id", "project_id"], "agent_runs", ["id", "project_id"]),
        Index("ix_arenas_campaign_id_created_at", "campaign_id", "created_at"),
    )


class RiskScan(Base):
    __tablename__ = "risk_scans"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID]
    campaign_id: Mapped[UUID]
    run_id: Mapped[UUID]
    market: Mapped[dict]
    source_kind: Mapped[str]
    source_id: Mapped[UUID | None]
    content: Mapped[dict]
    asset_ids: Mapped[list] = mapped_column(default=list)
    result: Mapped[dict | None]
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    __table_args__ = (
        _fk(["campaign_id", "project_id"], "campaigns", ["id", "project_id"]),
        _fk(["run_id", "project_id"], "agent_runs", ["id", "project_id"]),
        UniqueConstraint("id", "project_id"),
        CheckConstraint("source_kind IN ('content_version', 'adaptation', 'custom')", name="source_kind"),
        Index("ix_risk_scans_campaign_id_created_at", "campaign_id", "created_at"),
    )


class RiskFinding(Base):
    """A Risk Radar finding (RiskFinding in `payload`); people own the status afterwards."""

    __tablename__ = "risk_findings"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID]
    scan_id: Mapped[UUID]
    position: Mapped[int]
    payload: Mapped[dict]
    status: Mapped[str] = mapped_column(default="open")
    status_note: Mapped[str | None]
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow)

    __table_args__ = (
        _fk(["scan_id", "project_id"], "risk_scans", ["id", "project_id"]),
        CheckConstraint("status IN ('open', 'dismissed', 'resolved', 'applied')", name="status"),
        Index("ix_risk_findings_scan_id_position", "scan_id", "position"),
    )


class Asset(Base):
    """An uploaded file. Bytes live in the ASSET_STORAGE_BACKEND under `storage_name` (server-generated:
    `{owner_id}/{asset_id}`, the Storage object key; older rows used `{asset_id hex}.{extension}`)."""

    __tablename__ = "assets"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id"))
    kind: Mapped[str]
    filename: Mapped[str]
    content_type: Mapped[str]
    size_bytes: Mapped[int]
    sha256: Mapped[str]
    storage_name: Mapped[str] = mapped_column(unique=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    __table_args__ = (
        UniqueConstraint("id", "project_id"),
        CheckConstraint("kind IN ('image', 'audio')", name="kind"),
        Index("ix_assets_project_id_created_at", "project_id", "created_at"),
    )


class Embedding(Base):
    """A stored embedding (D-034). Vectors of different models, dimensions, or configs are never compared."""

    __tablename__ = "embeddings"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id"))
    source_kind: Mapped[str]
    source_id: Mapped[str]
    text: Mapped[str]
    meta: Mapped[dict] = mapped_column("metadata", default=dict)
    model: Mapped[str]
    dims: Mapped[int]
    config_version: Mapped[str]
    vector: Mapped[list]
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow)

    __table_args__ = (
        UniqueConstraint("project_id", "source_kind", "source_id", "model", "config_version"),
        Index("ix_embeddings_project_id_model_dims", "project_id", "model", "dims"),
    )


class AssetBlob(Base):
    """Asset bytes when ASSET_STORAGE_BACKEND=database (local development and tests; durable but bloats Postgres)."""

    __tablename__ = "asset_blobs"

    asset_id: Mapped[UUID] = mapped_column(primary_key=True)
    project_id: Mapped[UUID]
    data: Mapped[bytes] = mapped_column(LargeBinary)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    __table_args__ = (_fk(["asset_id", "project_id"], "assets", ["id", "project_id"]),)


# --- contract v3 (migration 0005): population studies and social simulation ------------------------------------
# One row per participant, interview, and post. Study and simulation rows share the run id and keep a
# `checkpoint` JSON that makes resume idempotent by batch or round index.


class Population(Base):
    __tablename__ = "populations"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID]
    study_id: Mapped[UUID]
    size: Mapped[int]
    regions: Mapped[list]
    groups: Mapped[list]  # PopulationGroup[]
    construction: Mapped[dict]  # PopulationConstruction
    limitations: Mapped[list] = mapped_column(default=list)
    mode: Mapped[str]
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    __table_args__ = (
        _fk(["study_id", "project_id"], "studies", ["id", "project_id"]),
        UniqueConstraint("id", "project_id"),
        CheckConstraint("size >= 1", name="size"),
        Index("ix_populations_project_id_created_at", "project_id", "created_at"),
    )


class Participant(Base):
    __tablename__ = "participants"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID]
    population_id: Mapped[UUID]
    group_id: Mapped[str]
    ordinal: Mapped[int]
    region_code: Mapped[str]
    region: Mapped[dict]
    interests: Mapped[list] = mapped_column(default=list)
    traits: Mapped[dict] = mapped_column(default=dict)
    evidence_ids: Mapped[list] = mapped_column(default=list)

    __table_args__ = (
        _fk(["population_id", "project_id"], "populations", ["id", "project_id"]),
        UniqueConstraint("population_id", "ordinal"),
        UniqueConstraint("id", "project_id"),
        Index("ix_participants_population_id_group_id", "population_id", "group_id"),
        Index("ix_participants_population_id_region_code", "population_id", "region_code"),
    )


class PopulationStudy(Base):
    """Shares its id with the population_study run."""

    __tablename__ = "population_studies"

    id: Mapped[UUID] = mapped_column(primary_key=True)
    project_id: Mapped[UUID]
    study_id: Mapped[UUID]
    campaign_id: Mapped[UUID]
    population_id: Mapped[UUID | None]  # set once the population is built (or at start when reused)
    content_version_id: Mapped[UUID]
    requested_participants: Mapped[int]
    interview_depth: Mapped[str]
    seed: Mapped[int]
    checkpoint: Mapped[dict] = mapped_column(default=dict)  # {"completed_batches": [...], "batch_size": n}
    result: Mapped[dict | None]
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow)

    __table_args__ = (
        _fk(["id", "project_id"], "agent_runs", ["id", "project_id"]),
        _fk(["study_id", "project_id"], "studies", ["id", "project_id"]),
        _fk(["population_id", "project_id"], "populations", ["id", "project_id"]),
        _fk(["content_version_id", "campaign_id"], "campaign_versions", ["id", "campaign_id"]),
        UniqueConstraint("id", "project_id"),
        CheckConstraint("interview_depth IN ('brief', 'standard', 'deep')", name="interview_depth"),
        Index("ix_population_studies_study_id_created_at", "study_id", "created_at"),
    )


class Interview(Base):
    __tablename__ = "interviews"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID]
    run_id: Mapped[UUID]  # the population study (= its run)
    participant_id: Mapped[UUID]
    batch_index: Mapped[int]
    group_id: Mapped[str]
    region_code: Mapped[str]
    status: Mapped[str]
    reaction: Mapped[str | None]
    payload: Mapped[dict]  # the full Interview (answers, comprehension, themes, concerns, ...)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    __table_args__ = (
        _fk(["run_id", "project_id"], "population_studies", ["id", "project_id"]),
        _fk(["participant_id", "project_id"], "participants", ["id", "project_id"]),
        UniqueConstraint("run_id", "participant_id"),
        CheckConstraint("status IN ('completed', 'failed')", name="status"),
        Index("ix_interviews_run_id_group_id", "run_id", "group_id"),
        Index("ix_interviews_run_id_reaction", "run_id", "reaction"),
        Index("ix_interviews_run_id_region_code", "run_id", "region_code"),
    )


class SocialSimulation(Base):
    """Shares its id with the social_simulation run."""

    __tablename__ = "social_simulations"

    id: Mapped[UUID] = mapped_column(primary_key=True)
    project_id: Mapped[UUID]
    population_study_id: Mapped[UUID]
    rounds_requested: Mapped[int]
    active_share: Mapped[float]
    feed_size: Mapped[int]
    seed: Mapped[int]
    checkpoint: Mapped[dict] = mapped_column(default=dict)  # {"completed_rounds": [...], "rounds": [summaries], "stances": {...}}
    result: Mapped[dict | None]
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow)

    __table_args__ = (
        _fk(["id", "project_id"], "agent_runs", ["id", "project_id"]),
        _fk(["population_study_id", "project_id"], "population_studies", ["id", "project_id"]),
        UniqueConstraint("id", "project_id"),
        CheckConstraint("rounds_requested BETWEEN 1 AND 5", name="rounds_requested"),
        Index("ix_social_simulations_population_study_id_created_at", "population_study_id", "created_at"),
    )


class SocialPost(Base):
    __tablename__ = "social_posts"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID]
    simulation_id: Mapped[UUID]
    round_index: Mapped[int]
    participant_id: Mapped[UUID]
    group_id: Mapped[str]
    action: Mapped[str]
    parent_post_id: Mapped[UUID | None] = mapped_column(ForeignKey("social_posts.id"))
    text: Mapped[str | None]
    stance: Mapped[str]
    previous_stance: Mapped[str | None]
    reason: Mapped[str | None]
    seen_post_ids: Mapped[list] = mapped_column(default=list)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    __table_args__ = (
        _fk(["simulation_id", "project_id"], "social_simulations", ["id", "project_id"]),
        _fk(["participant_id", "project_id"], "participants", ["id", "project_id"]),
        CheckConstraint("action IN ('post', 'comment', 'share', 'ignore')", name="action"),
        CheckConstraint("round_index BETWEEN 1 AND 5", name="round_index"),
        Index("ix_social_posts_simulation_id_round_index", "simulation_id", "round_index"),
        Index("ix_social_posts_simulation_id_group_id", "simulation_id", "group_id"),
    )


class GroupQuestion(Base):
    """A question put to a seeded sample of one group (README section 14.9); its answers are follow_ups rows."""

    __tablename__ = "group_questions"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID]
    population_study_id: Mapped[UUID]
    group_id: Mapped[str]
    question: Mapped[str]
    sample_size: Mapped[int]
    stance: Mapped[dict]  # ReactionDistribution over the sampled answers only
    summary: Mapped[str]
    sample_note: Mapped[str]
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    __table_args__ = (
        _fk(["population_study_id", "project_id"], "population_studies", ["id", "project_id"]),
        UniqueConstraint("id", "project_id"),
        Index("ix_group_questions_population_study_id_group_id", "population_study_id", "group_id"),
    )


class FollowUp(Base):
    """One in-character answer from one participant (direct question, or part of a group question)."""

    __tablename__ = "follow_ups"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID]
    population_study_id: Mapped[UUID]
    participant_id: Mapped[UUID]
    group_id: Mapped[str]
    group_question_id: Mapped[UUID | None]
    question: Mapped[str]
    answer: Mapped[str]
    stance: Mapped[str | None]
    memory_refs: Mapped[list] = mapped_column(default=list)
    model_id: Mapped[str | None]
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    __table_args__ = (
        _fk(["population_study_id", "project_id"], "population_studies", ["id", "project_id"]),
        _fk(["participant_id", "project_id"], "participants", ["id", "project_id"]),
        _fk(["group_question_id", "project_id"], "group_questions", ["id", "project_id"]),
        Index("ix_follow_ups_population_study_id_participant_id", "population_study_id", "participant_id"),
    )
