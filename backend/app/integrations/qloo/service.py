"""Qloo integration service: the typed interface the workflows (F) and the API (D) use.

Live mode runs verified `qloo exec` workflows (executor.py) with an optional cache. Demo
mode runs the same normalization over hand-authored envelopes (fixtures.py) and never
touches the cache. Methods never raise for provider problems; they return status "error"
with a QlooError.

Resolution rule. Qloo's find_tags reports status "ok" for any semantic-search candidates
(verified in harness 0.1.26) and gives no calibrated relevance score, so a candidate is not
proof of a match. A concept is `resolved` only when the top-ranked candidate's name is a
near-exact match for the query and no other returned candidate matches equally. Near-exact
means equal after NFKC, casefold, punctuation-to-space, whitespace collapse, and dropping a
trailing plural "s" from words longer than three letters. Otherwise the result is `ambiguous`
with the top candidates, which are never used downstream; no candidates is `unresolved`.
Entity search never resolves to a venue (`urn:entity:place`) automatically; the person can confirm one.
"""

import logging
import re
import time
import unicodedata
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from app.core.config import Settings
from app.integrations.qloo.cache import (
    CACHE_TTL,
    NORMALIZER_VERSION,
    CachedEntry,
    QlooCacheStore,
    cache_key,
    sha256_hex,
)
from app.integrations.qloo.executor import (
    Envelope,
    InsightsType,
    QlooError,
    QlooFailure,
    SubprocessExecutor,
    build_request,
    resolve_qloo_command,
    validate_query,
)
from app.integrations.qloo.fixtures import (
    FIXTURE_ID_PREFIX,
    FIXTURE_LIMITATION,
    FIXTURE_TIMESTAMP,
    FIXTURE_VALUE_DESCRIPTION,
    FixtureExecutor,
)
from app.integrations.qloo.rest import DEFAULT_BASE_URL, RestExecutor, normalize_base_url
from app.schemas.common import Market
from app.schemas.discovery import ConfirmedReference
from app.schemas.evidence import ClaimType, EntityRef, EvidenceProvenance, EvidenceType, RetrievalMode, SourceAttribute

log = logging.getLogger(__name__)

AFFINITY_LIMITATION = "Aggregate affinity; not evidence of demand, purchase intent, or individual preference."
AMBIGUOUS_LIMITATION = "Ambiguous: refine the term before relying on it."
UNRESOLVED_LIMITATION = "No usable Qloo match; any interpretation of this phrase is a hypothesis."
CONFIRMED_LIMITATION = "Chosen by the person among Qloo's candidates for this term, not matched automatically."
NOT_COMPARABLE_LIMITATION = "Affinity scores are relative to this request's signals; do not compare them across requests."
_NON_WORD = re.compile(r"[\W_]+")

_ATTRIBUTES = {
    "match_rank": ("Match rank", "Position in the returned candidates."),
    "affinity": (
        "Affinity",
        "Qloo affinity score as returned for this request, not rescaled. Relative to this request's signals; "
        "not a probability, and not evidence of demand or purchase intent.",
    ),
    "popularity": (
        "Popularity",
        "Qloo popularity value as returned, not rescaled. Relative popularity in Qloo's data; not market share or demand.",
    ),
}
_CACHEABLE = frozenset({"ok", "empty", "needs_input"})  # partial, degraded, and error results are never cached
DEMOGRAPHIC_DESCRIPTION = (
    "Qloo demographic affinity score as returned: positive means stronger-than-average alignment for this group, "
    "negative weaker. Not a share of the audience and not a probability."
)
DEMOGRAPHIC_LIMITATION = "Aggregate demographic affinity of an audience; it describes no individual."
TREND_LIMITATION = "Qloo popularity metrics describe Qloo's data over time, not sales or market demand."
TREND_FIELDS = (
    "population_percentile", "population_rank", "population_rank_velocity", "velocity_fold_change",
    "population_percent_delta",
)


class QlooEntity(BaseModel):
    entity_id: str
    name: str
    entity_type: str | None = None
    attributes: list[SourceAttribute] = Field(default_factory=list)

    def ref(self) -> EntityRef:
        return EntityRef(entity_id=self.entity_id, name=self.name, entity_type=self.entity_type)


class EvidenceDraft(BaseModel):
    """EvidenceRecord minus id, project_id, source_run_id, and created_at, which the caller adds."""

    model_config = ConfigDict(extra="forbid")

    evidence_type: EvidenceType
    claim_type: ClaimType
    title: str
    summary: str
    source_provider: str
    source_workflow: str | None
    source_reference: str | None
    subject: EntityRef | None
    related_entity: EntityRef | None
    attributes: list[SourceAttribute]
    method: str
    retrieval_mode: RetrievalMode
    is_live_data: bool
    retrieved_at: datetime | None
    limitations: list[str]
    provenance: EvidenceProvenance | None


class ResolvedConcept(BaseModel):
    query: str
    status: Literal["resolved", "ambiguous", "unresolved", "error"]
    match: QlooEntity | None = None
    candidates: list[QlooEntity] = Field(default_factory=list)
    evidence: list[EvidenceDraft] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    error: QlooError | None = None


class RelatedInterests(BaseModel):
    seed: QlooEntity
    status: Literal["ok", "empty", "partial", "error"]
    items: list[QlooEntity] = Field(default_factory=list)
    evidence: list[EvidenceDraft] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    error: QlooError | None = None


class DemographicSegment(BaseModel):
    dimension: Literal["age", "gender"]
    bucket: str  # as returned, e.g. "25_to_29", "female"
    affinity: float  # as returned; see DEMOGRAPHIC_DESCRIPTION


class AudienceDemographics(BaseModel):
    entity: QlooEntity
    status: Literal["ok", "empty", "error"]
    segments: list[DemographicSegment] = Field(default_factory=list)
    evidence: list[EvidenceDraft] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    error: QlooError | None = None


class TrendPoint(BaseModel):
    date: str
    population_percentile: float | None = None
    population_rank: float | None = None
    population_rank_velocity: float | None = None
    velocity_fold_change: float | None = None
    population_percent_delta: float | None = None


class EntityTrend(BaseModel):
    entity: QlooEntity
    status: Literal["ok", "empty", "error"]
    points: list[TrendPoint] = Field(default_factory=list)  # newest first, as Qloo returns them
    evidence: list[EvidenceDraft] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    error: QlooError | None = None


@dataclass
class _Lookup:
    workflow: str
    request: dict[str, Any]
    envelope: Envelope
    mode: RetrievalMode
    retrieved_at: datetime
    entities: list["QlooEntity"]
    notes: list[str]


class QlooService(Protocol):
    mode: Literal["live", "fixture"]

    def is_configured(self) -> bool: ...

    async def resolve_concept(
        self, query: str, *, limit: int = 5, confirmed: ConfirmedReference | None = None
    ) -> ResolvedConcept: ...

    async def related_interests(
        self, seed: QlooEntity, *, market: Market | None, limit: int = 10
    ) -> RelatedInterests: ...

    async def audience_demographics(self, entity: QlooEntity, *, limit: int = 10) -> AudienceDemographics: ...


class QlooCall(BaseModel):
    """One Qloo request made inside `record_calls()`, cache hits included."""

    workflow: str
    retrieval_mode: Literal["live", "cached", "fixture", "error"]
    status: str = Field(description="Envelope status, or the error code when the call failed.")
    duration_ms: int


_CALLS: ContextVar[list[QlooCall] | None] = ContextVar("qloo_calls", default=None)


@contextmanager
def record_calls() -> Iterator[list[QlooCall]]:
    """Collect every Qloo request made in this block (and tasks it starts), e.g. the calls of one population study."""
    calls: list[QlooCall] = []
    token = _CALLS.set(calls)
    try:
        yield calls
    finally:
        _CALLS.reset(token)


def _record(workflow: str, mode: Literal["live", "cached", "fixture", "error"], status: str, started: float) -> None:
    calls = _CALLS.get()
    if calls is not None:
        calls.append(QlooCall(workflow=workflow, retrieval_mode=mode, status=status,
                              duration_ms=int((time.perf_counter() - started) * 1000)))


class Executor(Protocol):
    def is_configured(self) -> bool: ...

    async def run(self, workflow: str, request: dict[str, Any]) -> Envelope: ...


def _match_key(value: str) -> str:
    """Near-exact comparison key: NFKC, casefold, punctuation to spaces, simple plural folding."""
    words = _NON_WORD.sub(" ", unicodedata.normalize("NFKC", value).casefold()).split()
    return " ".join(w[:-1] if len(w) > 3 and w.endswith("s") and not w.endswith("ss") else w for w in words)


def _select(term: str, entities: list[QlooEntity]) -> QlooEntity | None:
    """The top candidate, only when it is a near-exact and unique match. Never picks by rank alone."""
    key = _match_key(term)
    top, *rest = entities
    if _match_key(top.name) == key and all(_match_key(entity.name) != key for entity in rest):
        return top
    return None


def _utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)  # SQLite drops tzinfo


def _is_fixture_envelope(envelope: Envelope) -> bool:
    """True for anything produced by the demo fixtures: their transport or `fixture:` ids."""
    if envelope.execution.get("transport") == "fixture":
        return True
    return any(
        isinstance(item, dict) and str(item.get("entity_id") or item.get("id") or "").startswith(FIXTURE_ID_PREFIX)
        for item in envelope.results
    )


def _relevant(seed: QlooEntity, items: list[QlooEntity], raw: list[Any]) -> tuple[list[QlooEntity], list[str]]:
    """Semantic-relevance check for related entities, grounded in Qloo's own tagging.

    Tag seed: keep only entities whose Qloo tags include the seed tag. When the transport returns no entity tags
    (the harness drops them), membership rests on Qloo's filter and the result says so. Entity seed: the link
    is shared audience affinity, not topic, so the results are flagged for review."""
    if not _is_tag(seed):
        return items, [f"Related by shared audience affinity with {seed.name}, not by topic; review relevance before use."]
    tags = {str(r.get("entity_id") or r.get("id")): r.get("tag_ids") for r in raw if isinstance(r, dict)}
    if not any(isinstance(value, list) for value in tags.values()):
        return items, [(f"Relevance rests on Qloo's '{seed.name}' tag filter; this transport returns no entity tags "
                        "to re-check membership.")]
    kept = [item for item in items if seed.entity_id in (tags.get(item.entity_id) or [])]
    dropped = len(items) - len(kept)
    note = (f"{dropped} result(s) did not carry Qloo's '{seed.name}' tag and were dropped by the relevance check."
            if dropped else f"Every result carries Qloo's '{seed.name}' tag (relevance check).")
    return kept, [note]


def _kind_label(entity: QlooEntity) -> str:
    """'urn:entity:brand' or 'brand' -> 'brand'; unknown types read as 'interest'."""
    return (entity.entity_type or "interest").rsplit(":", 1)[-1].replace("_", " ") or "interest"


def _is_tag(entity: QlooEntity) -> bool:
    kind = entity.entity_type or ""
    return kind == "tag" or kind.startswith("urn:tag") or entity.entity_id.startswith("urn:tag:")


def _attribute(key: str, value: int | float, *, fixture: bool) -> SourceAttribute:
    label, description = _ATTRIBUTES[key]
    if fixture and key != "match_rank":
        description = FIXTURE_VALUE_DESCRIPTION
    return SourceAttribute(key=key, label=label, value=value, description=description)


def _entity(item: Any, position: int, *, fixture: bool, rank_key: str | None) -> QlooEntity | None:
    """Map one harness result item, keeping Qloo's id, name, and type as returned."""
    if not isinstance(item, dict):
        return None
    entity_id = item.get("entity_id") or item.get("id")
    name = item.get("name")
    if not (isinstance(entity_id, str) and entity_id.strip() and isinstance(name, str) and name.strip()):
        return None
    kind = next((value for value in (item.get("subtype"), item.get("type")) if isinstance(value, str) and value), None)
    attributes = []
    if rank_key:
        rank = item.get("rank")
        attributes.append(_attribute(rank_key, rank if isinstance(rank, int) else position, fixture=fixture))
    for key in ("affinity", "popularity"):
        value = item.get(key)
        if isinstance(value, int | float) and not isinstance(value, bool):
            attributes.append(_attribute(key, value, fixture=fixture))
    return QlooEntity(entity_id=entity_id, name=name, entity_type=kind, attributes=attributes)


def _entities(items: list[Any], *, fixture: bool, rank_key: str | None) -> tuple[list[QlooEntity], list[str]]:
    entities = [
        entity
        for position, item in enumerate(items, start=1)
        if (entity := _entity(item, position, fixture=fixture, rank_key=rank_key))
    ]
    skipped = len(items) - len(entities)
    return entities, [f"{skipped} Qloo result(s) without an id or name were left out."] if skipped else []


def _issue_candidates(envelope: Envelope) -> list[Any]:
    """Candidates a needs_input envelope lists under resolution.issues[].candidates."""
    issues = (envelope.resolution or {}).get("issues")
    if not isinstance(issues, list):
        return []
    return [
        candidate
        for issue in issues
        if isinstance(issue, dict) and isinstance(issue.get("candidates"), list)
        for candidate in issue["candidates"]
    ]


def _envelope_notes(envelope: Envelope) -> list[str]:
    notes = []
    if envelope.status in ("partial", "degraded"):
        notes.append(f"Qloo returned a {envelope.status} result: {(envelope.summary or 'no details given')[:300]}")
    notes +=[f"Qloo warning: {warning[:300]}" for warning in envelope.warnings[:5]]
    return notes


class HarnessQlooService:
    """QlooService over harness-format envelopes, live (subprocess) or demo (fixtures)."""

    def __init__(
        self,
        executor: Executor,
        *,
        mode: Literal["live", "fixture"],
        cache: QlooCacheStore | None = None,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        if mode == "live" and isinstance(executor, FixtureExecutor):
            raise ValueError("Live mode cannot use the demo fixture executor.")
        if mode == "fixture" and isinstance(executor, SubprocessExecutor):
            raise ValueError("Fixture mode never runs the live Qloo harness.")
        self.mode = mode
        self._executor = executor
        self._cache = cache if mode == "live" else None  # fixture results never touch the live cache
        self._now = now

    def is_configured(self) -> bool:
        return self._executor.is_configured()

    @property
    def transport(self) -> str:
        return getattr(self._executor, "transport", "unknown")

    async def _lookup(self, workflow: str, fields: dict[str, Any]) -> _Lookup:
        request = build_request(workflow, fields)
        envelope, mode, retrieved_at = await self._execute(workflow, request)
        entities, notes = _entities(
            envelope.results or _issue_candidates(envelope), fixture=mode == "fixture", rank_key="match_rank"
        )
        return _Lookup(workflow, request, envelope, mode, retrieved_at, entities, notes + _envelope_notes(envelope))

    async def resolve_concept(
        self, query: str, *, limit: int = 5, confirmed: ConfirmedReference | None = None
    ) -> ResolvedConcept:
        """Tag search (GET /v2/tags) first; entity search (GET /search) when no tag matches near-exactly.

        `confirmed` is the person's choice among the candidates (contracts README §14.2): it replaces name matching.
        The lookup that listed the candidates (cached in live mode) runs again so only an id Qloo actually returns for
        this term is used, with Qloo's own name and type; anything else falls back to normal matching with a note."""
        if confirmed is not None:
            try:
                term = validate_query(query)
                workflow = "find_tags" if confirmed.ref_kind == "tag" else "search_entities"
                lookup = await self._lookup(workflow, {"query": term, "limit": limit})
            except QlooFailure as failure:
                note = f"Qloo could not be queried ({failure.error.code}); the confirmed reference was not verified."
                return ResolvedConcept(query=query, status="error", error=failure.error, limitations=[note])
            match = next((entity for entity in lookup.entities if entity.entity_id == confirmed.ref_id), None)
            if match is not None:
                return self._resolved(query, term, lookup, match, confirmed=True)
            result = await self.resolve_concept(query, limit=limit)
            note = f"The confirmed {confirmed.ref_kind} is not among Qloo's candidates for '{term}', so it was not used."
            return result.model_copy(update={"limitations": [note, *result.limitations]})
        try:
            term = validate_query(query)
            tags = await self._lookup("find_tags", {"query": term, "limit": limit})
        except QlooFailure as failure:
            note = f"Qloo could not be queried ({failure.error.code}); nothing about this term was verified."
            return ResolvedConcept(query=query, status="error", error=failure.error, limitations=[note])
        match = _select(term, tags.entities) if tags.entities and tags.envelope.status != "needs_input" else None
        if match is not None:
            return self._resolved(query, term, tags, match)

        lookups = [tags]
        try:
            entities = await self._lookup("search_entities", {"query": term, "limit": limit})
        except QlooFailure as failure:
            tags.notes.append(f"Entity search failed ({failure.error.code}); only Qloo tags were checked.")
        else:
            lookups.append(entities)
            # A venue named like the phrase is a coincidence, not a cultural referent (live 2026-10-28: 'minimal
            # design' named an architecture firm). Venues stay listed as candidates the person can confirm.
            plausible = [entity for entity in entities.entities if not (entity.entity_type or "").endswith(":place")]
            match = _select(term, plausible) if plausible else None
            if match is not None:
                return self._resolved(query, term, entities, match)

        notes = [note for lookup in lookups for note in lookup.notes]
        with_candidates = [lookup for lookup in lookups if lookup.entities]
        if not with_candidates:
            reason = tags.envelope.summary if tags.envelope.status == "empty" and tags.envelope.summary else UNRESOLVED_LIMITATION
            return ResolvedConcept(query=query, status="unresolved", limitations=[reason[:300], *notes])
        evidence = []
        for lookup in with_candidates:
            noun = "tags" if lookup.workflow == "find_tags" else "entities"
            count = len(lookup.entities[:limit])
            summary = (
                f"Demo fixture: {count} plausible {noun} are listed; Nativeproof did not choose one."
                if lookup.mode == "fixture"
                else f"{count} plausible Qloo {noun} were returned; Nativeproof did not choose one."
            )
            title = f"Ambiguous match: '{term}'" if noun == "tags" else f"Ambiguous entity match: '{term}'"
            evidence.append(self._lookup_draft(lookup, title, summary, None))
        candidates = [entity for lookup in with_candidates for entity in lookup.entities][:limit]
        return ResolvedConcept(query=query, status="ambiguous", candidates=candidates, evidence=evidence,
                               limitations=[AMBIGUOUS_LIMITATION, *notes])

    def _resolved(
        self, query: str, term: str, lookup: _Lookup, match: QlooEntity, *, confirmed: bool = False
    ) -> ResolvedConcept:
        noun = "tag" if lookup.workflow == "find_tags" else _kind_label(match).replace("interest", "entity")
        how = "confirmed by the person among Qloo's candidates" if confirmed else "near-exact name match"
        summary = (
            f"Demo fixture: the concept '{term}' resolves to the {match.name} {noun} ({how})."
            if lookup.mode == "fixture"
            else f"The concept '{term}' resolved to the {match.name} {noun} ({how})."
        )
        verb = "Confirmed" if confirmed else "Resolved"
        title = f"{verb} tag: {match.name}" if noun == "tag" else f"{verb} {noun}: {match.name}"
        notes = [CONFIRMED_LIMITATION] if confirmed else []
        return ResolvedConcept(query=query, status="resolved", match=match,
                               evidence=[self._lookup_draft(lookup, title, summary, match)],
                               limitations=[AFFINITY_LIMITATION, *notes, *lookup.notes])

    def _lookup_draft(self, lookup: _Lookup, title: str, summary: str, subject: QlooEntity | None) -> EvidenceDraft:
        return self._draft(
            workflow=lookup.workflow, request=lookup.request, envelope=lookup.envelope, mode=lookup.mode,
            retrieved_at=lookup.retrieved_at, title=title, summary=summary, subject=subject, related=None,
            limitations=[*self._mode_notes(lookup.mode, lookup.retrieved_at), AFFINITY_LIMITATION,
                         *_envelope_notes(lookup.envelope)],
        )

    async def related_interests(
        self, seed: QlooEntity, *, market: Market | None, limit: int = 10, target_type: InsightsType = "brand"
    ) -> RelatedInterests:
        """Qloo Insights for `target_type` entities (live default: brand) related to the seed, never tags.

        A tag seed is a filter (`filter.tags`): verified live on 2026-10-28, a tag *signal* barely moved results
        (unrelated brands with identical affinity), while the filter returned topical outdoor brands. Results that
        do not carry the seed tag are dropped (semantic-relevance check).
        An entity seed is an audience-affinity signal and its results are flagged as such. The market is the
        audience-location signal."""
        fields: dict[str, Any] = {}
        try:
            self._refuse_fixture_ids(seed)
            fields = {"target_type": target_type, "limit": limit}
            if _is_tag(seed):
                fields["include_tags"] = [seed.entity_id]
                if market is None:  # the harness requires at least one signal
                    fields["signal_tags"] = [seed.entity_id]
            else:
                fields["signals"] = [seed.entity_id]
            if market is not None:
                fields["signal_location"] = validate_query(market.display_name)
            request = build_request("recommend", fields)
            envelope, mode, retrieved_at = await self._execute("recommend", request)
        except QlooFailure as failure:
            if market is not None and await self._location_rejected(failure, fields):
                note = (f"Qloo did not accept '{market.display_name}' as a location (the API answers HTTP 400 when no "
                        "locality matches), so no market-specific related interests were retrieved.")
                return RelatedInterests(seed=seed, status="empty", limitations=[AFFINITY_LIMITATION, note])
            note = f"Qloo could not be queried ({failure.error.code}); no related interests were retrieved."
            return RelatedInterests(seed=seed, status="error", error=failure.error, limitations=[note])

        if envelope.status == "needs_input":
            detail = (envelope.summary or "the input needs clarification")[:300]
            error = QlooError(
                code="QLOO_INVALID_REQUEST",
                message=f"Qloo could not use '{seed.name}' as a signal: {detail}",
                retryable=False,
            )
            return RelatedInterests(seed=seed, status="error", error=error, limitations=[error.message])

        items, notes = _entities(envelope.results, fixture=mode == "fixture", rank_key=None)
        limitations = [AFFINITY_LIMITATION, NOT_COMPARABLE_LIMITATION]
        relevance: list[str] = []
        if self.mode == "live":
            limitations.append(f"Related interests are Qloo {target_type} entities; Qloo's recommend workflow does not return tags.")
            if market is not None:
                limitations.append(
                    f"The market ({fields['signal_location']}) was sent as Qloo's audience-location signal: it weights "
                    "affinities toward audiences there and does not restrict results to that market."
                )
            items, relevance = _relevant(seed, items, envelope.results)
        limitations += relevance + notes + _envelope_notes(envelope)
        if not items:
            if envelope.status == "empty" and envelope.summary:
                limitations.append(envelope.summary[:300])
            return RelatedInterests(seed=seed, status="empty", limitations=limitations)

        evidence_limitations = [*self._mode_notes(mode, retrieved_at), AFFINITY_LIMITATION, *relevance,
                                *_envelope_notes(envelope)]
        evidence = [
            self._draft(
                workflow="recommend",
                request=request,
                envelope=envelope,
                mode=mode,
                retrieved_at=retrieved_at,
                title=f"Related {_kind_label(item)}: {item.name}",
                summary=(
                    f"Demo fixture: {item.name} stands in for a Qloo recommend result for audiences with a "
                    f"{seed.name} affinity." if mode == "fixture"
                    else f"{item.name} was returned as a related {_kind_label(item)} for audiences with a "
                    f"{seed.name} affinity."
                ),
                subject=seed,
                related=item,
                limitations=evidence_limitations,
            )
            for item in items
        ]
        status = "partial" if envelope.status in ("partial", "degraded") else "ok"
        return RelatedInterests(seed=seed, status=status, items=items, evidence=evidence, limitations=limitations)

    async def _location_rejected(self, failure: QlooFailure, fields: dict[str, Any]) -> bool:
        """True when the market location caused the failure. The REST transport sees Qloo's message; the harness
        reports any 4xx as QLOO_CONTRACT, so one probe without the location confirms the cause."""
        if failure.error.code == "QLOO_LOCALITY_NOT_FOUND":
            return True
        if failure.error.code != "QLOO_CONTRACT" or "signal_location" not in fields:
            return False
        try:
            probe = build_request("recommend", {k: v for k, v in fields.items() if k != "signal_location"})
            await self._execute("recommend", probe)
        except QlooFailure:
            return False
        return True

    def _refuse_fixture_ids(self, entity: QlooEntity) -> None:
        if self.mode == "live" and entity.entity_id.startswith(FIXTURE_ID_PREFIX):
            raise QlooFailure(QlooError(code="QLOO_INVALID_REQUEST", message="Demo fixture entities cannot be sent to Qloo.",
                                        retryable=False))

    async def _raw_lookup(self, workflow: str, fields: dict[str, Any]) -> _Lookup:
        request = build_request(workflow, fields)
        envelope, mode, retrieved_at = await self._execute(workflow, request)
        return _Lookup(workflow, request, envelope, mode, retrieved_at, [], _envelope_notes(envelope))

    async def audience_demographics(self, entity: QlooEntity, *, limit: int = 10) -> AudienceDemographics:
        """Aggregate demographic affinity of an entity's audience (Insights, filter.type=urn:demographics)."""
        try:
            self._refuse_fixture_ids(entity)
            if _is_tag(entity):
                raise QlooFailure(QlooError(code="QLOO_INVALID_REQUEST", retryable=False,
                                            message="The verified demographics workflow takes Qloo entities, not tags."))
            lookup = await self._raw_lookup("audience_demographics", {"entity": entity.entity_id, "limit": limit})
        except QlooFailure as failure:
            note = f"Qloo could not be queried ({failure.error.code}); no demographics were retrieved."
            return AudienceDemographics(entity=entity, status="error", error=failure.error, limitations=[note])
        block = next((item for item in lookup.envelope.results if isinstance(item, dict)), {})
        query = block.get("query") if isinstance(block.get("query"), dict) else {}
        segments = [
            DemographicSegment(dimension=dimension, bucket=str(bucket), affinity=float(score))  # type: ignore[arg-type]
            for dimension in ("age", "gender")
            for bucket, score in (query.get(dimension) or {}).items()
            if isinstance(score, int | float) and not isinstance(score, bool)
        ]
        limitations = [DEMOGRAPHIC_LIMITATION, *lookup.notes]
        if not segments:
            if lookup.envelope.status == "empty" and lookup.envelope.summary:
                limitations.append(lookup.envelope.summary[:300])
            return AudienceDemographics(entity=entity, status="empty", limitations=limitations)
        attributes = [
            SourceAttribute(key=f"{s.dimension}.{s.bucket}", label=f"{s.dimension.capitalize()}: {s.bucket.replace('_', ' ')}",
                            value=s.affinity, description=DEMOGRAPHIC_DESCRIPTION)
            for s in segments
        ]
        draft = self._draft(
            workflow="audience_demographics", request=lookup.request, envelope=lookup.envelope, mode=lookup.mode,
            retrieved_at=lookup.retrieved_at, title=f"Audience demographics: {entity.name}",
            summary=f"Demographic affinity scores for audiences of {entity.name}, as returned by Qloo.",
            subject=entity, related=None, attributes=attributes,
            limitations=[*self._mode_notes(lookup.mode, lookup.retrieved_at), DEMOGRAPHIC_LIMITATION, *lookup.notes],
        )
        return AudienceDemographics(entity=entity, status="ok", segments=segments, evidence=[draft], limitations=limitations)

    async def trends(
        self, entity: QlooEntity, *, entity_type: InsightsType, start_date: str, end_date: str, limit: int = 20
    ) -> EntityTrend:
        """Dated popularity points for one entity (GET /v2/trending). Real time series; never interpolated."""
        try:
            self._refuse_fixture_ids(entity)
            if _is_tag(entity):
                raise QlooFailure(QlooError(code="QLOO_INVALID_REQUEST", retryable=False,
                                            message="Qloo trending data is available for entities, not tags."))
            try:
                ordered = datetime.fromisoformat(start_date) <= datetime.fromisoformat(end_date)
            except ValueError:
                ordered = False
            if not ordered:
                raise QlooFailure(QlooError(code="QLOO_INVALID_REQUEST", retryable=False,
                                            message="Trend dates must be valid YYYY-MM-DD values, start before end."))
            lookup = await self._raw_lookup("trends", {"entity": entity.entity_id, "entity_type": entity_type,
                                                       "start_date": start_date, "end_date": end_date, "limit": limit})
        except QlooFailure as failure:
            note = f"Qloo could not be queried ({failure.error.code}); no trend data was retrieved."
            return EntityTrend(entity=entity, status="error", error=failure.error, limitations=[note])
        points = [
            TrendPoint(date=item["date"], **{
                field: float(item[field]) for field in TREND_FIELDS
                if isinstance(item.get(field), int | float) and not isinstance(item.get(field), bool)
            })
            for item in lookup.envelope.results
            if isinstance(item, dict) and isinstance(item.get("date"), str)
        ]
        limitations = [TREND_LIMITATION, *lookup.notes]
        if not points:
            if lookup.envelope.status == "empty" and lookup.envelope.summary:
                limitations.append(lookup.envelope.summary[:300])
            return EntityTrend(entity=entity, status="empty", limitations=limitations)
        latest = points[0]
        attributes = [
            SourceAttribute(key=field, label=field.replace("_", " ").capitalize(), value=getattr(latest, field),
                            description=f"Value for {latest.date} as returned by Qloo /v2/trending, not rescaled.")
            for field in TREND_FIELDS
            if getattr(latest, field) is not None
        ]
        draft = self._draft(
            workflow="trends", request=lookup.request, envelope=lookup.envelope, mode=lookup.mode,
            retrieved_at=lookup.retrieved_at, title=f"Popularity trend: {entity.name}",
            summary=f"{len(points)} dated popularity points for {entity.name} between {start_date} and {end_date}, "
            f"as returned by Qloo (latest {latest.date}).",
            subject=entity, related=None, attributes=attributes,
            limitations=[*self._mode_notes(lookup.mode, lookup.retrieved_at), TREND_LIMITATION, *lookup.notes],
        )
        return EntityTrend(entity=entity, status="ok", points=points, evidence=[draft], limitations=limitations)

    async def _execute(self, workflow: str, request: dict[str, Any]) -> tuple[Envelope, RetrievalMode, datetime]:
        key = cache_key(workflow, request)
        started = time.perf_counter()
        if self._cache is not None:
            cached = await self._cache_read(key)
            if cached is not None:
                log.info("qloo %s cache hit key=%s", workflow, key[:12])
                _record(workflow, "cached", cached[0].status, started)
                return cached[0], "cached", cached[1]
        try:
            envelope = await self._executor.run(workflow, request)
        except QlooFailure as failure:
            _record(workflow, "error", failure.error.code, started)
            raise
        _record(workflow, "fixture" if self.mode == "fixture" else "live", envelope.status, started)
        if self.mode == "fixture":
            return envelope, "fixture", FIXTURE_TIMESTAMP
        if _is_fixture_envelope(envelope):
            raise QlooFailure(QlooError(
                code="QLOO_INVALID_RESPONSE", message="A demo fixture result reached the live Qloo adapter and was rejected.",
                retryable=False,
            ))
        retrieved_at = self._now()
        if self._cache is not None and envelope.status in _CACHEABLE:
            entry = CachedEntry(
                key=key,
                workflow=workflow,
                request_hash=sha256_hex({"workflow": workflow, "input": request}),
                response=envelope.model_dump(mode="json"),
                response_hash=sha256_hex(envelope.results),
                retrieved_at=retrieved_at,
                expires_at=retrieved_at + CACHE_TTL[workflow],
            )
            try:
                await self._cache.put(entry)
            except Exception as exc:  # cache trouble must never fail a Qloo lookup
                log.warning("qloo cache write failed (QLOO_CACHE_ERROR): %s", type(exc).__name__)
        return envelope, "live", retrieved_at

    async def _cache_read(self, key: str) -> tuple[Envelope, datetime] | None:
        assert self._cache is not None
        try:
            entry = await self._cache.get(key)
            if entry is None or _utc(entry.expires_at) <= self._now():
                return None  # expired entries are never served
            envelope = Envelope.model_validate(entry.response)
            if _is_fixture_envelope(envelope):
                log.warning("qloo cache entry %s holds fixture data; ignored", key[:12])
                return None
            return envelope, _utc(entry.retrieved_at)
        except Exception as exc:  # unreadable or invalid entries count as a miss
            log.warning("qloo cache read failed (QLOO_CACHE_ERROR): %s", type(exc).__name__)
            return None

    @staticmethod
    def _mode_notes(mode: RetrievalMode, retrieved_at: datetime) -> list[str]:
        if mode == "fixture":
            return [FIXTURE_LIMITATION]
        if mode == "cached":
            return [f"Cached Qloo result retrieved {retrieved_at:%Y-%m-%d %H:%M} UTC; Qloo data may have changed since."]
        return []

    def _draft(
        self,
        *,
        workflow: str,
        request: dict[str, Any],
        envelope: Envelope,
        mode: RetrievalMode,
        retrieved_at: datetime,
        title: str,
        summary: str,
        subject: QlooEntity | None,
        related: QlooEntity | None,
        limitations: list[str],
        attributes: list[SourceAttribute] | None = None,
    ) -> EvidenceDraft:
        reference = related or subject
        return EvidenceDraft(
            evidence_type="qloo_source",
            claim_type="observed",
            title=title,
            summary=summary,
            source_provider="qloo",
            source_workflow=workflow,
            source_reference=reference.entity_id if reference else None,
            subject=subject.ref() if subject else None,
            related_entity=related.ref() if related else None,
            attributes=attributes if attributes is not None else list(reference.attributes) if reference else [],
            method="provider_result",
            retrieval_mode=mode,
            is_live_data=mode != "fixture",
            retrieved_at=retrieved_at,
            limitations=list(limitations),
            # Hashes identify a retrieved Qloo request/response; a hand-authored fixture has neither.
            provenance=EvidenceProvenance(
                request_hash=None if mode == "fixture" else sha256_hex({"workflow": workflow, "input": request}),
                response_hash=None if mode == "fixture" else sha256_hex(envelope.results),
                normalizer_version=NORMALIZER_VERSION,
                fixture_origin="hand_authored" if mode == "fixture" else None,
            ),
        )


def get_qloo_service(
    mode: Literal["live", "demo"], settings: Settings, cache: QlooCacheStore | None = None
) -> QlooService:
    """Demo projects get the fixture service (cache ignored). Live projects use the direct REST transport by
    default (`auto`, `rest`): measured live on 2026-10-28 at 1.2-1.6 s per call against 10-24 s for the harness,
    with identical results, and it returns entity tags for the relevance check. QLOO_TRANSPORT=harness selects
    the official harness (`qloo exec`)."""
    if mode == "demo":
        return HarnessQlooService(FixtureExecutor(), mode="fixture")
    if mode != "live":
        raise ValueError(f"Unknown Qloo service mode: {mode!r}")
    # QLOO_BASE_URL and QLOO_TRANSPORT are requested Settings fields; absent means defaults.
    transport = getattr(settings, "qloo_transport", None) or "auto"
    try:
        base_url = normalize_base_url(getattr(settings, "qloo_base_url", None))
    except ValueError as exc:
        log.error("Qloo disabled: %s", exc)
        return HarnessQlooService(RestExecutor(api_key=None, base_url=None, timeout_seconds=1), mode="live")
    if transport == "harness":
        executor: Executor = SubprocessExecutor(
            api_key=settings.qloo_api_key, command=resolve_qloo_command(settings.qloo_bin),
            timeout_seconds=settings.qloo_timeout_seconds, base_url=None if base_url == DEFAULT_BASE_URL else base_url,
        )
    else:
        executor = RestExecutor(
            api_key=settings.qloo_api_key, base_url=base_url, timeout_seconds=settings.qloo_timeout_seconds
        )
    return HarnessQlooService(executor, mode="live", cache=cache)
