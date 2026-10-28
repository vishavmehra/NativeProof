from typing import Literal

from app.schemas.common import ApiModel

DependencyStatus = Literal["configured", "not_configured", "available", "unavailable", "not_required"]


class Health(ApiModel):
    status: Literal["ok"]


class ReadinessDependencies(ApiModel):
    database: DependencyStatus
    llm_provider: DependencyStatus
    qloo: DependencyStatus


class ReadinessCapabilities(ApiModel):
    """Optional AI capabilities; the UI hides or explains features whose capability is not configured."""

    embeddings: DependencyStatus
    vision: DependencyStatus
    reranking: DependencyStatus


class Readiness(ApiModel):
    """Configuration-level readiness. `configured` does not mean a provider was reachable."""

    status: Literal["ready", "degraded", "not_ready"]
    dependencies: ReadinessDependencies
    capabilities: ReadinessCapabilities
    live_mode_available: bool
    demo_mode_available: bool
