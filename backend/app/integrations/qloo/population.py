"""Population evidence (contract v3, contracts/README.md §14.3) for the population builder.

Seeds are the references the discovery snapshot resolved (or the person confirmed), then the campaign concept and
reference terms under the same near-exact rule; ambiguous or unresolved terms are never used. Per study region,
each seed's related Qloo brands come from Insights with the region as the audience-location signal and the
relevance check applied (`HarnessQlooService.related_interests`). Demographics (`urn:demographics`) describe an
entity's audience in aggregate: they may ground a group, never a participant. Live results go through the Qloo
cache and every record carries provenance; demo projects use the labelled fixtures and never call Qloo.
"""

from datetime import UTC, datetime
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from app.integrations.qloo.service import EvidenceDraft, QlooCall, QlooEntity, QlooService, _is_tag, record_calls
from app.schemas.common import Market
from app.schemas.evidence import EvidenceRecord
from app.schemas.population import InterestRef

MAX_TERMS = 5
LOOKUP_WORKFLOWS = ("find_tags", "search_entities")
WEIGHT_DEFINITION = (
    "weight = 1 - index / count over the region's ordered interests (seeds first, then each seed's related entities "
    "in Qloo's returned order). Emphasis from evidence rank; not prevalence, share, or probability."
)
DEMOGRAPHICS_NOTE = (
    "Demographic evidence describes an entity's whole audience in aggregate, not a region and never a person: cite it "
    "on groups only."
)


class RegionInterests(BaseModel):
    region: Market
    interests: list[InterestRef]


class PopulationEvidence(BaseModel):
    evidence: list[EvidenceRecord] = Field(description="Records created here; discovery records are cited by id.")
    regions: list[RegionInterests]
    demographic_evidence_ids: list[UUID] = Field(description="Group-level aggregate evidence only.")
    calls: list[QlooCall] = Field(description="Every Qloo request this collection made, cache hits included.")
    grounded: bool = Field(description="False when no reference could be resolved; groups are then hypotheses.")
    weight_definition: str = WEIGHT_DEFINITION
    limitations: list[str]


async def collect_population_evidence(
    qloo: QlooService,
    *,
    project_id: UUID,
    run_id: UUID,
    regions: list[Market],
    concept: str | None,
    reference_terms: list[str],
    discovery_evidence: list[EvidenceRecord],
    max_seeds: int = 3,
    related_per_region: int = 5,
    max_demographics: int = 2,
    now: datetime | None = None,
) -> PopulationEvidence:
    """Live calls are bounded: at most MAX_TERMS resolutions (1-2 calls each, cached after a discovery), one Insights
    call per seed and region (max_seeds x regions), and max_demographics demographics calls."""
    now = now or datetime.now(UTC)
    evidence: list[EvidenceRecord] = []
    limitations: list[str] = []

    def keep(drafts: list[EvidenceDraft]) -> list[EvidenceRecord]:
        made = [EvidenceRecord.model_validate({**d.model_dump(), "id": uuid4(), "project_id": project_id,
                                               "source_run_id": run_id, "created_at": now}) for d in drafts]
        evidence.extend(made)
        return made

    with record_calls() as calls:
        seeds: dict[str, tuple[QlooEntity, list[UUID]]] = {}
        live = qloo.mode == "live"
        for record in discovery_evidence:  # resolved or confirmed references from the discovery snapshot
            subject = record.subject
            if record.source_workflow in LOOKUP_WORKFLOWS and subject and subject.entity_id and record.is_live_data == live:
                entity = QlooEntity(entity_id=subject.entity_id, name=subject.name, entity_type=subject.entity_type)
                seeds.setdefault(entity.entity_id, (entity, []))[1].append(record.id)

        unique: dict[str, str] = {}
        for raw in [concept or "", *reference_terms]:
            if raw.strip():
                unique.setdefault(raw.strip().casefold(), raw.strip())  # first spelling wins
        terms = list(unique.values())
        for term in terms[:MAX_TERMS]:
            if len(seeds) >= max_seeds:
                break
            resolved = await qloo.resolve_concept(term)
            if resolved.status == "resolved" and resolved.match is not None:
                if resolved.match.entity_id not in seeds:
                    seeds[resolved.match.entity_id] = (resolved.match, [r.id for r in keep(resolved.evidence)])
            elif resolved.status == "error":
                limitations.append(f"'{term}' could not be looked up in Qloo, so it does not ground the population.")
            else:
                limitations.append(f"'{term}' is {resolved.status} in Qloo, so it does not ground the population.")
        if len(terms) > MAX_TERMS:
            limitations.append(f"Only the first {MAX_TERMS} terms were looked up.")
        chosen = list(seeds.values())[:max_seeds]

        by_region: list[RegionInterests] = []
        demographic_targets: list[QlooEntity] = []
        for region in regions:
            interests = list(chosen)
            for seed, _ in chosen:
                related = await qloo.related_interests(seed, market=region, limit=related_per_region)
                made = keep(related.evidence)
                if related.status in ("error", "empty"):
                    reason = related.limitations[-1] if related.limitations else related.status
                    limitations.append(f"{region.display_name}: no related interests for {seed.name} ({reason})")
                for item in related.items:
                    if any(entity.entity_id == item.entity_id for entity, _ in interests):
                        continue
                    ids = [r.id for r in made if r.related_entity and r.related_entity.entity_id == item.entity_id]
                    interests.append((item, ids))
                    if len(demographic_targets) < max_demographics and item not in demographic_targets:
                        demographic_targets.append(item)
            count = len(interests)
            by_region.append(RegionInterests(region=region, interests=[
                InterestRef(ref_id=entity.entity_id, ref_kind="tag" if _is_tag(entity) else "entity", name=entity.name,
                            weight=round(1 - index / count, 3), evidence_ids=ids)
                for index, (entity, ids) in enumerate(interests)
            ]))

        demographic_ids: list[UUID] = []
        for entity in demographic_targets:
            demographics = await qloo.audience_demographics(entity)
            if demographics.status == "ok":
                demographic_ids += [r.id for r in keep(demographics.evidence)]
            else:
                reason = demographics.limitations[-1] if demographics.limitations else demographics.status
                limitations.append(f"No demographic evidence for {entity.name} ({reason})")
        if demographic_ids:
            limitations.append(DEMOGRAPHICS_NOTE)

    if not chosen:
        limitations.insert(0, "No reference resolved in Qloo, so the population is not grounded in cultural evidence; "
                              "its groups are hypotheses.")
    return PopulationEvidence(evidence=evidence, regions=by_region, demographic_evidence_ids=demographic_ids,
                              calls=calls, grounded=bool(chosen), limitations=list(dict.fromkeys(limitations)))
