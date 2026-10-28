from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field

from app.schemas.common import ApiModel, DataMode, ErrorCode, Page

RunType = Literal[
    "market_discovery",
    "campaign_rehearsal",
    "campaign_adaptation",
    "campaign_evaluation",
    "cultural_profile",
    "campaign_arena",
    "risk_scan",
    "market_comparison",
    "population_study",
    "social_simulation",
]
RunStatus = Literal["queued", "running", "completed", "partial", "failed", "cancelled"]
TERMINAL_RUN_STATUSES: frozenset[str] = frozenset({"completed", "partial", "failed", "cancelled"})


class RunProgress(ApiModel):
    """Best-effort stage information from the backend. Never a time estimate."""

    stage: str
    completed_steps: int = Field(ge=0)
    total_steps: int = Field(ge=1)
    message: str


class RunError(ApiModel):
    code: ErrorCode
    message: str = Field(description="Safe, user-facing explanation, including whether results were saved.")
    stage: str | None = None
    retryable: bool


class RunResultRef(ApiModel):
    """Where to fetch the result once the run is completed or partial."""

    resource: Literal[
        "discovery",
        "rehearsal",
        "adaptations",
        "evaluation",
        "cultural_profile",
        "arena",
        "risk_scan",
        "market_comparison",
        "population_study",
        "social_simulation",
    ]
    ids: list[UUID]
    url: str = Field(description="API path of the result resource, e.g. /api/v1/projects/{id}/discoveries/{run_id}.")


class Run(ApiModel):
    id: UUID
    project_id: UUID
    campaign_id: UUID | None
    study_id: UUID | None
    run_type: RunType
    status: RunStatus
    mode: DataMode
    progress: RunProgress | None
    result: RunResultRef | None
    error: RunError | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None


class RunAccepted(ApiModel):
    run_id: UUID
    status: RunStatus
    run_type: RunType
    status_url: str


class RunPage(Page[Run]):
    pass
