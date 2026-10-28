"""Cultural Trend Watch: timestamped discovery snapshots and deterministic comparisons."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, StringConstraints

from app.schemas.common import ApiModel, DataMode, Market, Page
from app.schemas.evidence import EntityRef

ChangeKind = Literal["added", "removed", "status_changed", "attribute_changed", "unchanged"]


class SnapshotCreate(ApiModel):
    discovery_run_id: UUID = Field(description="A completed or partial discovery run to keep as a snapshot.")
    label: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]


class Snapshot(ApiModel):
    id: UUID
    project_id: UUID
    campaign_id: UUID | None
    discovery_run_id: UUID
    label: str
    market: Market
    product_category: str
    reference_terms: list[str]
    captured_at: datetime = Field(description="When the discovery run completed, not when the snapshot was saved.")
    mode: DataMode
    reference_count: int
    evidence_count: int
    created_at: datetime


class SnapshotPage(Page[Snapshot]):
    pass


class TrendComparisonCreate(ApiModel):
    base_snapshot_id: UUID
    target_snapshot_id: UUID


class ObservationChange(ApiModel):
    kind: ChangeKind
    reference_key: str = Field(description="The query term or entity id the observations are matched on.")
    entity: EntityRef | None
    attribute: str | None
    before: str | None
    after: str | None
    delta: float | None = Field(description="Numeric difference in the source's own units; null when not numeric.")
    evidence_ids_before: list[UUID]
    evidence_ids_after: list[UUID]


class Implication(ApiModel):
    text: str
    claim_type: Literal["hypothesis"] = "hypothesis"
    based_on: list[str] = Field(description="reference_keys of the changes this implication rests on.")


class TrendComparisonSummary(ApiModel):
    id: UUID
    project_id: UUID
    base_snapshot_id: UUID
    target_snapshot_id: UUID
    comparable: bool
    change_count: int
    created_at: datetime


class TrendComparison(TrendComparisonSummary):
    """Deterministic diff of two snapshots; no model call and no invented history."""

    base: Snapshot
    target: Snapshot
    comparability_notes: list[str]
    changes: list[ObservationChange]
    implications: list[Implication]
    limitations: list[str]


class TrendComparisonPage(Page[TrendComparisonSummary]):
    pass
