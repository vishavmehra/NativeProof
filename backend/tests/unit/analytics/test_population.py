"""Population analytics (contracts/README §14.3-14.7): deterministic expansion, tallies, similarity, network, views."""

from uuid import uuid4

from app.analytics.population import (
    TRAITS,
    allocate,
    batches,
    diffusion_view,
    distribution,
    expand_participants,
    group_similarity,
    landscape_view,
    normalize_label,
    peer_network,
    reaction_map_view,
    stance_shifts,
    theme_counts,
)
from app.schemas.campaigns import CampaignContent
from app.schemas.common import Market
from app.schemas.population import InterestRef, Interview, InterviewAnswer, PopulationGroup, SocialPost

JP = Market(country_code="JP", display_name="Japan")
EV = [uuid4(), uuid4()]


def interest(ref: str, weight: float) -> InterestRef:
    return InterestRef(ref_id=ref, ref_kind="tag", name=ref.title(), weight=weight, evidence_ids=[])


def group(gid: str, share: float, interests: list[InterestRef], evidence=()) -> PopulationGroup:
    return PopulationGroup(id=gid, label=gid.upper(), description="d", region=JP, share=share, participant_count=0,
                           interests=interests, evidence_ids=list(evidence))


GROUPS = [group("grp-1", 0.5, [interest("hiking", 1.0), interest("camping", 0.6)], EV[:1]),
          group("grp-2", 0.3, [interest("hiking", 0.4), interest("design", 1.0)], EV),
          group("grp-3", 0.2, [interest("cooking", 1.0)])]


def interview(group_id: str, reaction, *, status="completed", themes=(), concerns=(), answer="ok") -> Interview:
    return Interview(id=uuid4(), run_id=uuid4(), participant_id=uuid4(), group_id=group_id, region=JP,
                     content_version_id=uuid4(), status=status, answers=[InterviewAnswer(question_id="first_impression",
                     question="q", answer=answer)], reaction=reaction if status == "completed" else None,
                     comprehension="understood" if status == "completed" else None, themes=list(themes),
                     concerns=list(concerns), misunderstanding=None, model_id=None, evidence_ids=[])


def test_allocation_is_exact_and_largest_remainder():
    assert allocate([0.5, 0.3, 0.2], 10) == [5, 3, 2]
    assert sum(allocate([1, 1, 1], 20)) == 20 and allocate([1, 1, 1], 20) == [7, 7, 6]


def test_expansion_is_deterministic_and_uses_only_the_four_knobs():
    pid = uuid4()
    groups_a, people_a = expand_participants(pid, GROUPS, 25, seed=42)
    _, people_b = expand_participants(pid, GROUPS, 25, seed=42)
    assert [p.model_dump() for p in people_a] == [p.model_dump() for p in people_b]
    assert [g.participant_count for g in groups_a] == [13, 7, 5] and len(people_a) == 25  # tie on .5: lower index
    assert [p.ordinal for p in people_a] == list(range(25))
    for p in people_a:
        assert set(p.traits) == set(TRAITS) and all(p.traits[k] in TRAITS[k] for k in TRAITS)
        source = next(g for g in GROUPS if g.id == p.group_id)
        assert {i.ref_id for i in p.interests} <= {i.ref_id for i in source.interests}
    _, other_seed = expand_participants(pid, GROUPS, 25, seed=7)
    assert [p.traits for p in other_seed] != [p.traits for p in people_a]
    assert [len(b) for b in batches(people_a, 10)] == [10, 10, 5]


def test_distribution_uses_completed_interviews_as_denominator():
    rows = [interview("grp-1", "positive"), interview("grp-1", "positive"), interview("grp-1", "confused"),
            interview("grp-1", None, status="failed")]
    d = distribution(rows)
    assert (d.denominator, d.failed) == (3, 1)
    assert d.counts == {"positive": 2, "mixed": 0, "neutral": 0, "negative": 0, "confused": 1}
    assert d.rates["positive"] == round(2 / 3, 4) and distribution([]).rates["positive"] == 0.0


def test_theme_tallies_normalize_labels_and_count_each_interview_once():
    rows = [interview("grp-1", "positive", themes=["Price!", " price ", "Trail use"]),
            interview("grp-1", "negative", themes=["PRICE"]), interview("grp-1", None, status="failed", themes=["price"])]
    counts = theme_counts(rows, "themes")
    assert [(t.label, t.count, t.share) for t in counts] == [("Price!", 2, 1.0), ("Trail use", 1, 0.5)]
    assert normalize_label('  "Escape"  ') == "escape"


def test_group_similarity_is_cosine_over_interest_weights():
    assert group_similarity(GROUPS[0], GROUPS[0]) == 1.0
    assert group_similarity(GROUPS[0], GROUPS[2]) == 0.0
    expected = round((1.0 * 0.4) / ((1.0**2 + 0.6**2) ** 0.5 * (0.4**2 + 1.0**2) ** 0.5), 4)
    assert group_similarity(GROUPS[0], GROUPS[1]) == expected
    assert group_similarity(GROUPS[0], group("empty", 0.1, [])) is None


def test_peer_network_is_seeded_mostly_within_group_and_bounded():
    _, people = expand_participants(uuid4(), GROUPS, 40, seed=42)
    net = peer_network(people, degree=6, seed=42)
    assert net == peer_network(people, degree=6, seed=42)
    by_id = {p.id: p for p in people}
    within = sum(by_id[q].group_id == by_id[p].group_id for p, qs in net.items() for q in qs)
    assert all(len(qs) == 6 and p not in qs and len(set(qs)) == 6 for p, qs in net.items())
    assert within / sum(len(qs) for qs in net.values()) >= 0.6


def test_stance_shifts_count_changed_participants_only():
    a, b, c = uuid4(), uuid4(), uuid4()
    assert stance_shifts({a: "positive", b: "negative", c: None}, {a: "negative", b: "negative", c: "positive"}) == 1


def test_views_explain_every_weight_and_edge():
    groups, _ = expand_participants(uuid4(), GROUPS, 20, seed=1)
    landscape = landscape_view(groups, is_demo=True)
    assert all(e.provenance for e in landscape.edges)
    assert all(e.weight_definition for e in landscape.edges if e.weight is not None)
    assert {e.relation for e in landscape.edges} >= {"in_region", "has_interest", "similar_to", "shares_evidence"}
    assert all(n.is_demo for n in landscape.nodes)
    content = CampaignContent(headline="Find your next great escape", body="Built for you.")
    rows = [interview("grp-1", "positive", themes=["escape"], answer="I like 'Find your next great escape'."),
            interview("grp-2", "confused", themes=["escape", "price"])]
    reaction_map = reaction_map_view(groups, rows, content, is_demo=False, recommendations=["Name the product."])
    rel = {(e.source, e.relation, e.target) for e in reaction_map.edges}
    assert ("group:grp-1", "reacted_to", "element:headline") in rel and ("group:grp-2", "feels", "reaction:confused") in rel
    assert all(e.weight_definition for e in reaction_map.edges if e.weight is not None)
    first = SocialPost(id=uuid4(), round_index=1, participant_id=uuid4(), group_id="grp-1", action="post", parent_post_id=None,
                       text="Great trails", previous_stance="neutral", stance="positive", reason="peers liked it",
                       seen_post_ids=[])
    reply = SocialPost(id=uuid4(), round_index=1, participant_id=uuid4(), group_id="grp-2", action="comment",
                       parent_post_id=first.id, text="Agreed", previous_stance="neutral", stance="positive", reason=None,
                       seen_post_ids=[first.id])
    diffusion = diffusion_view(groups, [first, reply], 1, is_demo=False)
    rel = {(e.source, e.relation, e.target) for e in diffusion.edges}
    assert ("group:grp-1", "influenced", "group:grp-2") in rel and (f"post:{reply.id}", "replied_to", f"post:{first.id}") in rel
    bounded = landscape_view(groups, is_demo=False, limit=2)
    assert bounded.truncated and len(bounded.nodes) == 2
