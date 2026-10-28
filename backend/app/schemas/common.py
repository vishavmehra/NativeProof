"""Shared primitives for the Nativeproof HTTP contract.

Contract-owned: the integration owner approves every change in app/schemas/, because
contracts/openapi.json and the frontend's generated types are built from these models.
"""

from datetime import datetime
from typing import Annotated, Generic, Literal, TypeVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints


class ApiModel(BaseModel):
    """Base for every contract model.

    Unknown fields are rejected instead of ignored, and response schemas mark
    defaulted fields as required because responses always include them.
    """

    model_config = ConfigDict(extra="forbid", json_schema_serialization_defaults_required=True)


Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
Label = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=60)]
Term = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
ShortText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)]
MediumText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]
TermList = Annotated[list[Term], Field(max_length=30)]
CountryCode = Annotated[str, StringConstraints(pattern=r"^[A-Z]{2}$")]
Score = Annotated[float, Field(ge=0, le=100)]

DataMode = Literal["live", "demo"]
Dimension = Literal["clarity", "brand_fidelity", "cultural_relevance", "cultural_risk"]
DIMENSIONS: tuple[Dimension, ...] = ("clarity", "brand_fidelity", "cultural_relevance", "cultural_risk")
ConfidenceLabel = Literal["insufficient", "limited", "moderate"]

ErrorCode = Literal[
    "VALIDATION_ERROR",
    "UNAUTHENTICATED",
    "FORBIDDEN",
    "NOT_FOUND",
    "CONFLICT",
    "RATE_LIMITED",
    "PROVIDER_ERROR",
    "PROVIDER_TIMEOUT",
    "PROVIDER_NOT_CONFIGURED",
    "UNSUPPORTED_CAPABILITY",
    "RUN_FAILED",
    "RUN_INTERRUPTED",
    "INTERNAL_ERROR",
]


class Market(ApiModel):
    country_code: CountryCode = Field(description="ISO 3166-1 alpha-2 code, uppercase.")
    display_name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]


MarketList = Annotated[list[Market], Field(max_length=10)]


class ErrorDetail(ApiModel):
    field: str | None = Field(default=None, description="Dotted path of the offending field, when applicable.")
    message: str


class ErrorBody(ApiModel):
    code: ErrorCode
    message: str
    details: list[ErrorDetail] = []
    request_id: str


class ErrorResponse(ApiModel):
    error: ErrorBody


ItemT = TypeVar("ItemT")


class Page(ApiModel, Generic[ItemT]):
    items: list[ItemT]
    limit: int
    offset: int
    total: int


RiskSeverity = Literal["low", "medium", "high"]
RiskCategory = Literal[
    "stereotype",
    "sensitivity",
    "ambiguity",
    "brand_inconsistency",
    "unsupported_claim",
    "constraint_violation",
    "visual_context",
    "other",
]


class RiskFlag(ApiModel):
    severity: RiskSeverity
    category: RiskCategory
    description: str
    source: Literal["deterministic_check", "model_assessment"] = Field(
        description="Deterministic checks are verified rules; model assessments are interpretations."
    )


class DimensionScores(ApiModel):
    """0-100 per dimension. cultural_risk: higher means more risk. Null when not assessed."""

    clarity: Score | None = None
    brand_fidelity: Score | None = None
    cultural_relevance: Score | None = None
    cultural_risk: Score | None = None


class Usage(ApiModel):
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    estimated_cost_usd: float | None = Field(
        default=None, description="Null when the provider reports no usage or verified pricing is unknown."
    )


class Sampling(ApiModel):
    """Generation settings actually sent to the model; null fields were not set."""

    temperature: float | None = None
    top_p: float | None = None
    seed: int | None = None


class StepTrace(ApiModel):
    """One executed workflow stage; the provenance Proof displays."""

    stage: str
    agent: str
    status: Literal["completed", "failed", "skipped"]
    provider: str | None = Field(default=None, description="qloo, nebius, openrouter, fixture, or nativeproof.")
    model_id: str | None = None
    prompt_version: str | None = None
    schema_version: str | None = None
    latency_ms: int | None = None
    retries: int = 0
    fallback_used: bool = False
    sampling: Sampling | None = None
    usage: Usage | None = None
    error_code: str | None = None


class RunMetadata(ApiModel):
    run_id: UUID
    mode: DataMode
    started_at: datetime | None = None
    completed_at: datetime | None = None
    steps: list[StepTrace] = []
