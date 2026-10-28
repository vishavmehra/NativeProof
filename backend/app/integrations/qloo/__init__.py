"""Qloo integration. Public interface: get_qloo_service and the result models (docs/04, appendix)."""

from app.integrations.qloo.cache import CachedEntry, InMemoryQlooCache, QlooCacheStore
from app.integrations.qloo.executor import QlooError
from app.integrations.qloo.population import PopulationEvidence, RegionInterests, collect_population_evidence
from app.integrations.qloo.service import (
    AudienceDemographics,
    DemographicSegment,
    EntityTrend,
    EvidenceDraft,
    QlooCall,
    QlooEntity,
    QlooService,
    RelatedInterests,
    ResolvedConcept,
    TrendPoint,
    get_qloo_service,
    record_calls,
)

__all__ = [
    "AudienceDemographics",
    "CachedEntry",
    "DemographicSegment",
    "EntityTrend",
    "EvidenceDraft",
    "InMemoryQlooCache",
    "PopulationEvidence",
    "QlooCacheStore",
    "QlooCall",
    "QlooEntity",
    "QlooError",
    "QlooService",
    "RegionInterests",
    "RelatedInterests",
    "ResolvedConcept",
    "TrendPoint",
    "collect_population_evidence",
    "get_qloo_service",
    "record_calls",
]
