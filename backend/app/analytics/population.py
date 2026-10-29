"""Deterministic population analytics (contracts/README §14.3-14.7). Pure functions, no model calls.

Participants are expanded from groups with a seed, so one population id always yields the same people. Tallies use
`rates = counts / denominator`, where the denominator is completed interviews and failures are reported beside it.
Graph views are built only from the records passed in; every weighted edge states its weight definition and every
edge states its provenance.
"""

import math
import random
import re
from collections import Counter
from collections.abc import Collection, Iterable, Mapping, Sequence
from datetime import UTC, datetime
from uuid import NAMESPACE_URL, UUID, uuid5

from app.schemas.common import Market
from app.schemas.population import (
    GraphView,
    GroupResult,
    Interview,
    InterestRef,
    LegendItem,
    Participant,
    PopulationGroup,
    ReactionCategory,
    GroupShift,
    ReactionDistribution,
    RegionResult,
    SocialPost,
    SocialRoundSummary,
    ThemeCount,
    ViewEdge,
    ViewNode,
)

CONFIG_VERSION = "population-v1"
REACTIONS: tuple[ReactionCategory, ...] = ("positive", "mixed", "neutral", "negative", "confused")
# The only synthetic variation knobs (README §14.3): no demographic or sensitive trait is ever invented.
TRAITS: dict[str, tuple[str, ...]] = {
    "adoption_style": ("early adopter", "mainstream", "late adopter"),
    "price_sensitivity": ("low", "medium", "high"),
    "media_habit": ("social-first", "search-first", "video-first", "print and outdoor"),
    "tone_preference": ("understated", "expressive", "practical"),
}
SIMILARITY_DEFINITION = (
    "Cosine similarity of two groups' interest-weight vectors over Qloo ids (missing ids count as 0); 0 = no shared "
    "weighted interests, 1 = identical weighting. Not a measure of real audience overlap."
)
SIMILARITY_THRESHOLD = 0.2
NETWORK_METHOD = (
    "Each participant links to `degree` peers ranked by shared-interest overlap (Jaccard over interest ids), about "
    "three quarters inside its own group and the rest across groups; ties are broken with the run seed."
)
PEER_SIMILARITY_DEFINITION = "Jaccard overlap of two participants' interest ids (shared / combined)."


# --- Population construction -------------------------------------------------------------------------------------


def allocate(shares: Sequence[float], size: int) -> list[int]:
    """Largest-remainder allocation of `size` participants by group share (shares are normalized here)."""
    total = sum(shares) or 1.0
    exact = [size * s / total for s in shares]
    counts = [math.floor(x) for x in exact]
    for i in sorted(range(len(shares)), key=lambda i: (-(exact[i] - counts[i]), i))[: size - sum(counts)]:
        counts[i] += 1
    return counts


def _weighted_subset(rng: random.Random, interests: Sequence[InterestRef], k: int) -> list[InterestRef]:
    pool, chosen = list(interests), []
    while pool and len(chosen) < k:
        pick = rng.choices(range(len(pool)), weights=[max(i.weight, 1e-6) for i in pool])[0]
        chosen.append(pool.pop(pick))
    return sorted(chosen, key=lambda i: -i.weight)


def expand_participants(
    population_id: UUID, groups: Sequence[PopulationGroup], size: int, seed: int, *, group_only: Collection[UUID] = ()
) -> tuple[list[PopulationGroup], list[Participant]]:
    """Deterministic expansion: same population id, groups, size, and seed give the same participants.

    `group_only` evidence (aggregate demographics) grounds a group and is never copied to a participant."""
    counts = allocate([g.share for g in groups], size)
    updated, participants, ordinal = [], [], 0
    for group, count in zip(groups, counts):
        updated.append(group.model_copy(update={"participant_count": count}))
        for k in range(count):
            rng = random.Random(f"{seed}:{group.id}:{k}")
            subset = _weighted_subset(rng, group.interests, max(1, min(3, len(group.interests)))) if group.interests else []
            participants.append(Participant(
                id=uuid5(NAMESPACE_URL, f"nativeproof-participant:{population_id}:{ordinal}"), population_id=population_id,
                group_id=group.id, ordinal=ordinal, region=group.region, interests=subset,
                traits={key: rng.choice(values) for key, values in TRAITS.items()},
                evidence_ids=[i for i in group.evidence_ids if i not in group_only],
            ))
            ordinal += 1
    return updated, participants


def batches(participants: Sequence[Participant], batch_size: int) -> list[list[Participant]]:
    ordered = sorted(participants, key=lambda p: p.ordinal)
    return [ordered[i : i + batch_size] for i in range(0, len(ordered), batch_size)]


# --- Tallies -----------------------------------------------------------------------------------------------------


def distribution(interviews: Iterable[Interview]) -> ReactionDistribution:
    rows = list(interviews)
    done = [i for i in rows if i.status == "completed" and i.reaction is not None]
    counts = Counter(i.reaction for i in done)
    denominator = len(done)
    return ReactionDistribution(
        denominator=denominator, failed=sum(1 for i in rows if i.status == "failed"),
        counts={r: counts.get(r, 0) for r in REACTIONS},
        rates={r: round(counts.get(r, 0) / denominator, 4) if denominator else 0.0 for r in REACTIONS},
    )


def stance_distribution(stances: Iterable[ReactionCategory | None]) -> ReactionDistribution:
    values = [s for s in stances if s is not None]
    counts = Counter(values)
    return ReactionDistribution(
        denominator=len(values), failed=0, counts={r: counts.get(r, 0) for r in REACTIONS},
        rates={r: round(counts.get(r, 0) / len(values), 4) if values else 0.0 for r in REACTIONS},
    )


_EDGE_PUNCT = re.compile(r"^[\W_]+|[\W_]+$")


def normalize_label(text: str) -> str:
    """Case-folded, whitespace-collapsed, edge punctuation removed: 'Price!' and ' price ' tally together."""
    return _EDGE_PUNCT.sub("", " ".join(text.split()).casefold())


def theme_counts(interviews: Iterable[Interview], field: str, limit: int | None = None) -> list[ThemeCount]:
    """Tally labels stored on completed interviews (`themes`, `concerns`, or `misunderstanding`); each interview
    counts a label once. share = count / completed interviews in scope."""
    done = [i for i in interviews if i.status == "completed"]
    counts: Counter[str] = Counter()
    first_label: dict[str, str] = {}
    examples: dict[str, list[UUID]] = {}
    for interview in done:
        raw = getattr(interview, field)
        labels = [raw] if isinstance(raw, str) else list(raw or [])
        for key in dict.fromkeys(k for k in (normalize_label(x) for x in labels) if k):
            counts[key] += 1
            first_label.setdefault(key, next(" ".join(x.split()) for x in labels if normalize_label(x) == key))
            examples.setdefault(key, []).append(interview.id)
    ranked = sorted(counts, key=lambda k: (-counts[k], k))[:limit]
    return [ThemeCount(label=first_label[k], count=counts[k], share=round(counts[k] / len(done), 4) if done else 0.0,
                       example_interview_ids=examples[k][:3]) for k in ranked]


def group_results(groups: Sequence[PopulationGroup], interviews: Sequence[Interview], limit: int = 10) -> list[GroupResult]:
    out = []
    for g in groups:
        mine = [i for i in interviews if i.group_id == g.id]
        out.append(GroupResult(
            group_id=g.id, label=g.label, region=g.region, distribution=distribution(mine),
            themes=theme_counts(mine, "themes", limit), concerns=theme_counts(mine, "concerns", limit),
            misunderstandings=theme_counts(mine, "misunderstanding", limit),
        ))
    return out


def region_results(regions: Sequence[Market], interviews: Sequence[Interview]) -> list[RegionResult]:
    return [RegionResult(region=r, distribution=distribution(i for i in interviews if i.region.country_code == r.country_code))
            for r in regions]


def stance_shifts(before: dict[UUID, ReactionCategory | None], after: dict[UUID, ReactionCategory | None]) -> int:
    return sum(1 for pid, stance in after.items() if before.get(pid) is not None and stance != before.get(pid))


def round_summary(
    round_index: int, posts: Sequence[SocialPost], before: dict[UUID, ReactionCategory | None],
    after: dict[UUID, ReactionCategory | None],
) -> SocialRoundSummary:
    """Deterministic tallies of one stored round. Themes stay empty: posts store no theme labels (README §14.6)."""
    mine = [p for p in posts if p.round_index == round_index]
    actions = Counter(p.action for p in mine)
    return SocialRoundSummary(
        round_index=round_index, active_participants=len({p.participant_id for p in mine}),
        actions={a: actions.get(a, 0) for a in ("post", "comment", "share", "ignore")},
        stance=stance_distribution(after.values()), shifts=stance_shifts(before, after), themes=[],
    )


def group_shifts(
    groups: Sequence[PopulationGroup], participants: Sequence[Participant], before: dict[UUID, ReactionCategory | None],
    after: dict[UUID, ReactionCategory | None],
) -> list[GroupShift]:
    members = {g.id: [p.id for p in participants if p.group_id == g.id] for g in groups}
    return [GroupShift(group_id=g.id, label=g.label, before=stance_distribution(before.get(i) for i in members[g.id]),
                       after=stance_distribution(after.get(i) for i in members[g.id])) for g in groups]


# --- Similarity and the peer network --------------------------------------------------------------------------------


def group_similarity(a: PopulationGroup, b: PopulationGroup) -> float | None:
    """Cosine over interest weights (SIMILARITY_DEFINITION); None when either group has no interests."""
    va, vb = {i.ref_id: i.weight for i in a.interests}, {i.ref_id: i.weight for i in b.interests}
    if not va or not vb:
        return None
    dot = sum(w * vb.get(k, 0.0) for k, w in va.items())
    norm = math.sqrt(sum(w * w for w in va.values())) * math.sqrt(sum(w * w for w in vb.values()))
    return round(dot / norm, 4) if norm else None


def landscape_similarity(groups: Sequence[PopulationGroup], threshold: float = SIMILARITY_THRESHOLD) -> list[tuple[str, str, float]]:
    pairs = []
    for i, a in enumerate(groups):
        for b in groups[i + 1 :]:
            score = group_similarity(a, b)
            if score is not None and score >= threshold:
                pairs.append((a.id, b.id, score))
    return pairs


def _jaccard(a: Participant, b: Participant) -> float:
    sa, sb = {i.ref_id for i in a.interests}, {i.ref_id for i in b.interests}
    return len(sa & sb) / len(sa | sb) if sa | sb else 0.0


def peer_network(participants: Sequence[Participant], degree: int, seed: int, within_share: float = 0.75) -> dict[UUID, list[UUID]]:
    """Directed, seeded k-neighbour lists: whose posts each participant can see."""
    ordered = sorted(participants, key=lambda p: p.ordinal)
    network: dict[UUID, list[UUID]] = {}
    for p in ordered:
        rng = random.Random(f"{seed}:net:{p.ordinal}")
        tie = {q.id: rng.random() for q in ordered if q.id != p.id}

        def ranked(pool: list[Participant]) -> list[UUID]:
            return [q.id for q in sorted(pool, key=lambda q: (-_jaccard(p, q), tie[q.id]))]

        same = ranked([q for q in ordered if q.group_id == p.group_id and q.id != p.id])
        other = ranked([q for q in ordered if q.group_id != p.group_id])
        k_within = min(len(same), round(degree * within_share))
        picks = same[:k_within] + other[: degree - k_within]
        if len(picks) < degree:  # small groups: top up from whichever pool has peers left
            picks += [q for q in same[k_within:] + other[degree - k_within :] if q not in picks][: degree - len(picks)]
        network[p.id] = picks
    return network


def active_participants(participants: Sequence[Participant], share: float, seed: int, round_index: int) -> list[Participant]:
    ordered = sorted(participants, key=lambda p: p.ordinal)
    k = max(1, round(len(ordered) * share))
    return sorted(random.Random(f"{seed}:round:{round_index}").sample(ordered, k), key=lambda p: p.ordinal)


# --- Graph views ----------------------------------------------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(UTC)


def _node(id_: str, kind: str, label: str, *, is_demo: bool, is_synthetic: bool = False, group_id: str | None = None,
          region: str | None = None, size: float | None = None, facts: dict | None = None, resource: str | None = None,
          resource_id: str | None = None) -> ViewNode:
    return ViewNode(id=id_, kind=kind, label=label, group_id=group_id, region=region, size=size, facts=facts or {},
                    resource=resource, resource_id=resource_id, is_synthetic=is_synthetic, is_demo=is_demo)


def _edge(source: str, target: str, relation: str, provenance: str, weight: float | None = None,
          definition: str | None = None) -> ViewEdge:
    return ViewEdge(id=f"{relation}:{source}->{target}", source=source, target=target, relation=relation, weight=weight,
                    weight_definition=definition if weight is not None else None, provenance=provenance)


def _bounded(nodes: list[ViewNode], edges: list[ViewEdge], limit: int | None) -> tuple[list[ViewNode], list[ViewEdge], bool]:
    if limit is None or len(nodes) <= limit:
        return nodes, edges, False
    keep = {n.id for n in nodes[:limit]}
    return nodes[:limit], [e for e in edges if e.source in keep and e.target in keep], True


def landscape_view(groups: Sequence[PopulationGroup], *, is_demo: bool, limit: int | None = None,
                   threshold: float = SIMILARITY_THRESHOLD) -> GraphView:
    """Graph B: groups, their regions and interests; similar_to above the threshold; shared-evidence links."""
    nodes, edges, seen = [], [], set()
    for g in groups:
        nodes.append(_node(f"group:{g.id}", "audience_group", g.label, is_demo=is_demo, is_synthetic=True, group_id=g.id,
                           region=g.region.country_code, size=float(g.participant_count),
                           facts={"participants": g.participant_count, "share": g.share, "interests": len(g.interests)}))
    for g in groups:
        region_id = f"region:{g.region.country_code}"
        if region_id not in seen:
            seen.add(region_id)
            nodes.append(_node(region_id, "region", g.region.display_name, is_demo=is_demo, region=g.region.country_code))
        edges.append(_edge(f"group:{g.id}", region_id, "in_region", "PopulationGroup.region"))
        for i in g.interests:
            interest_id = f"interest:{i.ref_id}"
            if interest_id not in seen:
                seen.add(interest_id)
                nodes.append(_node(interest_id, "interest", i.name, is_demo=is_demo, facts={"ref_kind": i.ref_kind}))
            edges.append(_edge(f"group:{g.id}", interest_id, "has_interest", "PopulationGroup.interests", i.weight,
                               "Interest weight derived from Qloo evidence rank (0-1)."))
    for a_id, b_id, score in landscape_similarity(groups, threshold):
        edges.append(_edge(f"group:{a_id}", f"group:{b_id}", "similar_to",
                           f"cosine over PopulationGroup.interests weights, shown at >= {threshold}", score, SIMILARITY_DEFINITION))
    for i, a in enumerate(groups):
        for b in groups[i + 1 :]:
            shared = set(a.evidence_ids) & set(b.evidence_ids)
            if shared:
                edges.append(_edge(f"group:{a.id}", f"group:{b.id}", "shares_evidence", "PopulationGroup.evidence_ids",
                                   float(len(shared)), "Number of evidence records cited by both groups."))
    nodes, edges, truncated = _bounded(nodes, edges, limit)
    limitations = ["Groups are synthetic archetypes; similarity compares their configured interests, not real audiences."]
    if truncated:
        limitations.append("Showing a bounded subgraph; use the list endpoints for everything.")
    if not any(e.relation == "similar_to" for e in edges):
        limitations.append("No group pair reached the similarity threshold; only shared-evidence links are drawn.")
    legend = [LegendItem(kind="audience_group", label="Audience group", description="Synthetic archetype (size = participants)."),
              LegendItem(kind="region", label="Region", description="Market the group was assigned to."),
              LegendItem(kind="interest", label="Interest", description="Qloo tag or entity cited by the group.")]
    return GraphView(view="audience_landscape", nodes=nodes, edges=edges, legend=legend, truncated=truncated,
                     limitations=limitations, generated_at=_now())


ELEMENTS = ("headline", "body", "call_to_action")


def reaction_map_view(groups: Sequence[PopulationGroup], interviews: Sequence[Interview], content, *, is_demo: bool,
                      recommendations: Sequence[str] = (), limit: int | None = None, theme_limit: int = 8) -> GraphView:
    """Graph C: campaign elements, groups, reactions, themes, cited evidence, and recommendations."""
    nodes, edges = [], []
    done = [i for i in interviews if i.status == "completed"]
    for field in ELEMENTS:
        text = getattr(content, field, None)
        if text:
            nodes.append(_node(f"element:{field}", "campaign_element", text[:80], is_demo=is_demo, facts={"field": field}))
    for reaction in REACTIONS:
        nodes.append(_node(f"reaction:{reaction}", "reaction", reaction, is_demo=is_demo, is_synthetic=True,
                           size=float(sum(1 for i in done if i.reaction == reaction))))
    themes = theme_counts(done, "themes", theme_limit)
    for t in themes:
        nodes.append(_node(f"theme:{normalize_label(t.label)}", "theme", t.label, is_demo=is_demo, is_synthetic=True,
                           size=float(t.count), facts={"count": t.count, "share": t.share}))
    evidence_seen: set[UUID] = set()
    for g in groups:
        mine = [i for i in done if i.group_id == g.id]
        nodes.append(_node(f"group:{g.id}", "audience_group", g.label, is_demo=is_demo, is_synthetic=True, group_id=g.id,
                           region=g.region.country_code, size=float(len(mine))))
        dist = distribution(mine)
        for reaction in REACTIONS:
            if dist.counts[reaction]:
                edges.append(_edge(f"group:{g.id}", f"reaction:{reaction}", "feels", "Interview.reaction tallies",
                                   dist.rates[reaction], "Share of the group's completed interviews with this reaction."))
        for field in ELEMENTS:
            text = getattr(content, field, None)
            mentions = sum(1 for i in mine if text and any(text.casefold() in a.answer.casefold() for a in i.answers))
            if mentions:
                edges.append(_edge(f"group:{g.id}", f"element:{field}", "reacted_to",
                                   "Interview.answers quote the element text (case-insensitive match)", float(mentions),
                                   "Number of the group's interviews that quote this element."))
        for t in theme_counts(mine, "themes"):
            key = normalize_label(t.label)
            if any(n.id == f"theme:{key}" for n in nodes):
                edges.append(_edge(f"group:{g.id}", f"theme:{key}", "mentions", "Interview.themes tallies",
                                   float(t.count), "Number of the group's interviews that name this theme."))
        for evidence_id in g.evidence_ids:
            if evidence_id not in evidence_seen:
                evidence_seen.add(evidence_id)
                nodes.append(_node(f"evidence:{evidence_id}", "evidence", "Evidence record", is_demo=is_demo,
                                   resource="evidence", resource_id=str(evidence_id)))
            edges.append(_edge(f"evidence:{evidence_id}", f"group:{g.id}", "supports", "PopulationGroup.evidence_ids"))
    for n, text in enumerate(recommendations, 1):
        nodes.append(_node(f"recommendation:{n}", "recommendation", text[:120], is_demo=is_demo, is_synthetic=True,
                           facts={"claim_type": "interpreted"}))
    nodes, edges, truncated = _bounded(nodes, edges, limit)
    limitations = ["Reactions and themes are tallies of AI-generated interviews, not real people."]
    if truncated:
        limitations.append("Showing a bounded subgraph; use the interview list for everything.")
    legend = [LegendItem(kind="campaign_element", label="Campaign element", description="Text shown to participants."),
              LegendItem(kind="audience_group", label="Audience group",
                         description="Synthetic archetype (size = completed interviews)."),
              LegendItem(kind="reaction", label="Reaction", description="Interview reaction category (size = interviews)."),
              LegendItem(kind="theme", label="Theme", description="Normalized theme label (size = interviews naming it)."),
              LegendItem(kind="evidence", label="Evidence", description="Stored evidence record cited by a group."),
              LegendItem(kind="recommendation", label="Recommendation",
                         description="Suggested next step (model interpretation).")]
    return GraphView(view="reaction_map", nodes=nodes, edges=edges, legend=legend, truncated=truncated,
                     limitations=limitations, generated_at=_now())


def diffusion_view(groups: Sequence[PopulationGroup], posts: Sequence[SocialPost], round_index: int, *, is_demo: bool,
                   limit: int | None = None, interview_groups: Mapping[UUID, str] | None = None) -> GraphView:
    """Group-level influence flows for one round, plus that round's bounded post subgraph.

    A feed (SocialPost.seen_post_ids) cites posts from earlier rounds and, from round 1 on, peers' interviews, so
    `posts` must hold every round of the simulation and `interview_groups` maps the study's interview ids to their
    group. A feed item that resolves to neither is skipped, never guessed.
    """
    interview_groups = interview_groups or {}
    by_id = {p.id: p for p in posts}
    current = [p for p in posts if p.round_index == round_index]
    nodes = [_node(f"group:{g.id}", "audience_group", g.label, is_demo=is_demo, is_synthetic=True, group_id=g.id,
                   region=g.region.country_code) for g in groups]
    flows: Counter[tuple[str, str]] = Counter()
    for post in current:
        for seen in post.seen_post_ids:
            source = by_id[seen].group_id if seen in by_id else interview_groups.get(seen)
            if source is not None:
                flows[(source, post.group_id)] += 1
    edges = [_edge(f"group:{a}", f"group:{b}", "influenced",
                   "SocialPost.seen_post_ids (author group of the seen post or interview -> reader group)", float(n),
                   "Number of feed items from the source group (posts or interviews) shown to the target group this round.")
             for (a, b), n in sorted(flows.items())]
    shown: set[UUID] = set()

    def add_post(post: SocialPost) -> None:
        if post.id in shown:
            return
        shown.add(post.id)
        label = (post.text or post.action)[:80]
        nodes.append(_node(f"post:{post.id}", "post", label if post.round_index == round_index else
                           f"Round {post.round_index}: {label}"[:80], is_demo=is_demo, is_synthetic=True,
                           group_id=post.group_id, facts={"action": post.action, "stance": post.stance, "round": post.round_index}))

    for post in current:
        if post.action == "ignore":
            continue
        add_post(post)
        if post.parent_post_id and post.parent_post_id in by_id:
            add_post(by_id[post.parent_post_id])
            edges.append(_edge(f"post:{post.id}", f"post:{post.parent_post_id}", "replied_to", "SocialPost.parent_post_id"))
        interviews_seen = Counter(interview_groups[s] for s in post.seen_post_ids if s in interview_groups)
        for group_id, n in sorted(interviews_seen.items()):
            edges.append(_edge(f"group:{group_id}", f"post:{post.id}", "influenced",
                               "SocialPost.seen_post_ids (interviews by the source group)", float(n),
                               "Number of the source group's interviews in this post's feed."))
        for seen in post.seen_post_ids:
            if seen in by_id:
                add_post(by_id[seen])
                edges.append(_edge(f"post:{seen}", f"post:{post.id}", "influenced", "SocialPost.seen_post_ids"))
    nodes, edges, truncated = _bounded(nodes, edges, limit)
    limitations = ["Simulated social dynamics: illustrative, not a forecast. Agents share one model."]
    if truncated:
        limitations.append("Showing a bounded subgraph; use the post list for everything.")
    legend = [LegendItem(kind="audience_group", label="Audience group", description="Synthetic archetype."),
              LegendItem(kind="post", label="Post", description="A simulated post, comment, or share in this round.")]
    return GraphView(view="social_diffusion", nodes=nodes, edges=edges, legend=legend, truncated=truncated,
                     limitations=limitations, generated_at=_now())
