"""Contract v3 in demo mode (deterministic): population studies, interviews, follow-ups, social simulation,
graph views, and isolation (contracts/README.md §14).

Each test is skipped, not xfailed, while a handler it needs is still the contract stub, and flips to live the moment
D replaces the stub (see `v3_support.needs`).
"""

from collections import Counter
from typing import Any

import httpx

from app.schemas.population import (
    CampaignComparison,
    FollowUpAnswer,
    FollowUpPage,
    GraphView,
    GroupQuestionResult,
    InterviewPage,
    ParticipantDetail,
    ParticipantPage,
    Population,
    PopulationStudyPage,
    SocialPostPage,
    SocialSimulationResult,
)
from app.schemas.runs import RunPage
from tests.integration import invariants as inv
from tests.integration._support import API, expect_error, fetch_all, parse, start_run, wait_for_run
from tests.integration.journey import create_demo, discover
from tests.integration.v3_support import (
    CORE_QUESTIONS,
    FOLLOW_UPS,
    ROUTES,
    SENSITIVE,
    check_distribution,
    check_graph,
    check_node_resources,
    needs,
    needs_workflow,
    run_population_study,
    tally,
)

R = ROUTES
STUDY_ROUTES = (R.start_population_study, R.get_population_study, R.list_interviews)
POPULATION_WORKFLOW = needs_workflow("run_population_study")
SOCIAL_WORKFLOW = needs_workflow("run_population_study", "run_social_simulation")


async def demo_with_evidence(client: httpx.AsyncClient, headers: dict[str, str]) -> Any:
    journey = await create_demo(client, headers, check=False)
    await discover(client, journey, check=False)
    return journey


async def all_interviews(client: httpx.AsyncClient, headers: dict[str, str], study_id: Any, **params: Any) -> list[Any]:
    return await fetch_all(client, f"{API}/population-studies/{study_id}/interviews", headers, InterviewPage, **params)


# --------------------------------------------------------------------------- population study


@needs(*STUDY_ROUTES)
@POPULATION_WORKFLOW
async def test_population_study_completes_with_honest_tallies(qa_client: httpx.AsyncClient, alice: dict[str, str]) -> None:
    journey = await demo_with_evidence(qa_client, alice)
    run, result = await run_population_study(qa_client, alice, journey.study.id, discovery_run_id=str(journey.discovery_run.id))
    assert result.id == run.id and result.mode == "demo" and result.status in ("completed", "partial")
    assert result.requested_participants == 40
    inv.check_demo_run_metadata(result.run_metadata, run.id, "population_study")
    inv.check_demo_evidence(result.evidence, journey.project_id)
    disclosure = result.disclosure
    assert disclosure.is_synthetic is True and disclosure.independent_human_sample is False and disclosure.shared_model_note
    check_distribution(result.overall, "overall")
    assert (result.overall.denominator, result.overall.failed) == (result.completed_interviews, result.failed_interviews)
    assert result.completed_interviews + result.failed_interviews == result.requested_participants
    if result.failed_interviews:
        assert result.status == "partial" and result.limitations, "failed interviews make the study partial, with a reason"

    interviews = await all_interviews(qa_client, alice, result.id)
    assert len(interviews) == result.requested_participants, "every participant has exactly one stored interview"
    assert len({i.participant_id for i in interviews}) == len(interviews), "duplicate interviews for one participant"
    completed = [i for i in interviews if i.status == "completed"]
    assert all(i.is_synthetic for i in interviews)
    for interview in completed:
        ids = [a.question_id for a in interview.answers]
        assert ids[: len(CORE_QUESTIONS)] == list(CORE_QUESTIONS), f"interview {interview.id}: core protocol {ids}"
        assert len(ids) == len(CORE_QUESTIONS) + FOLLOW_UPS["brief"]
        assert interview.reaction is not None and interview.content_version_id == journey.version_id
    # Aggregates are deterministic tallies over the stored interviews (§14.4).
    assert tally(i.reaction for i in completed) == Counter(result.overall.counts), "overall counts != stored interviews"
    for group in result.by_group:
        check_distribution(group.distribution, f"group {group.group_id}")
        members = [i for i in completed if i.group_id == group.group_id]
        assert tally(i.reaction for i in members) == Counter(group.distribution.counts), f"group {group.group_id} tally"
    assert sum(g.distribution.denominator for g in result.by_group) == result.overall.denominator
    for region in result.by_region:
        check_distribution(region.distribution, f"region {region.region.country_code}")
    for theme in result.themes:
        assert theme.count == sum(theme.label in i.themes for i in completed), f"theme {theme.label!r} count"
        assert abs(theme.share - theme.count / max(1, len(completed))) <= 0.0006


@needs(*STUDY_ROUTES)
@POPULATION_WORKFLOW
async def test_interviews_paginate_and_filter(qa_client: httpx.AsyncClient, alice: dict[str, str]) -> None:
    journey = await demo_with_evidence(qa_client, alice)
    _, result = await run_population_study(qa_client, alice, journey.study.id)
    path = f"{API}/population-studies/{result.id}/interviews"
    first = parse(InterviewPage, await qa_client.get(path, params={"limit": 7}, headers=alice))
    second = parse(InterviewPage, await qa_client.get(path, params={"limit": 7, "offset": 7}, headers=alice))
    assert (first.total, len(first.items), second.offset) == (result.requested_participants, 7, 7)
    assert not {i.id for i in first.items} & {i.id for i in second.items}, "pages overlap"
    group = result.by_group[0]
    by_group = await all_interviews(qa_client, alice, result.id, group_id=group.group_id)
    assert by_group and all(i.group_id == group.group_id for i in by_group)
    for reaction, count in result.overall.counts.items():
        items = await all_interviews(qa_client, alice, result.id, reaction=reaction)
        assert len(items) == count and all(i.reaction == reaction for i in items), f"reaction filter {reaction}"
    region = result.by_region[0].region.country_code
    assert all(i.region.country_code == region for i in await all_interviews(qa_client, alice, result.id, region=region))
    expect_error(await qa_client.get(path, params={"limit": 101}, headers=alice), 422, "VALIDATION_ERROR")


@needs(*STUDY_ROUTES, R.get_population, R.list_participants, R.list_population_studies)
@POPULATION_WORKFLOW
async def test_population_is_deterministic_and_reusable(qa_client: httpx.AsyncClient, alice: dict[str, str]) -> None:
    journey = await demo_with_evidence(qa_client, alice)
    _, first = await run_population_study(qa_client, alice, journey.study.id)
    population = parse(Population, await qa_client.get(f"{API}/populations/{first.population_id}", headers=alice))
    assert population.mode == "demo" and population.size == 40 and 3 <= population.group_count == len(population.groups) <= 12
    assert sum(g.participant_count for g in population.groups) == population.size
    assert abs(sum(g.share for g in population.groups) - 1) <= 0.01
    if not population.construction.grounded:
        assert population.limitations, "an ungrounded population says so"
    participants = await fetch_all(qa_client, f"{API}/populations/{population.id}/participants", alice, ParticipantPage)
    assert sorted(p.ordinal for p in participants) == list(range(population.size)), "ordinals are 0..size-1"
    groups = {g.id for g in population.groups}
    for participant in participants:
        assert participant.is_synthetic and participant.group_id in groups
        assert set(participant.traits) <= {"adoption_style", "price_sensitivity", "media_habit", "tone_preference"}
        assert not any(SENSITIVE.search(str(v)) for v in participant.traits.values()), f"participant {participant.ordinal}: demographic trait"
    one_group = await fetch_all(
        qa_client, f"{API}/populations/{population.id}/participants", alice, ParticipantPage, group_id=population.groups[0].id
    )
    assert len(one_group) == population.groups[0].participant_count

    # Reuse: identical people (same ids, ordinals, profiles) across campaign versions.
    _, reused = await run_population_study(qa_client, alice, journey.study.id, population_id=str(population.id))
    assert reused.population_id == population.id
    again = await fetch_all(qa_client, f"{API}/populations/{population.id}/participants", alice, ParticipantPage)
    assert [p.model_dump() for p in again] == [p.model_dump() for p in participants]
    assert {i.participant_id for i in await all_interviews(qa_client, alice, reused.id)} == {p.id for p in participants}

    # Fixed seed: a fresh population with the same seed has the same profiles and the same tallies.
    _, fresh = await run_population_study(qa_client, alice, journey.study.id)
    assert fresh.population_id != population.id
    twins = await fetch_all(qa_client, f"{API}/populations/{fresh.population_id}/participants", alice, ParticipantPage)

    def profile(p: Any) -> tuple[Any, ...]:
        return (p.ordinal, p.group_id, p.region.country_code, sorted(i.ref_id for i in p.interests), sorted(p.traits.items()))

    assert [profile(p) for p in twins] == [profile(p) for p in participants], "same seed, different participants"
    assert fresh.overall.counts == first.overall.counts, "tallies are not deterministic for a fixed seed"
    page = parse(PopulationStudyPage, await qa_client.get(f"{API}/studies/{journey.study.id}/population-studies", headers=alice))
    assert page.total == 3


@needs(R.start_population_study)
async def test_population_size_limits(qa_client: httpx.AsyncClient, alice: dict[str, str]) -> None:
    journey = await create_demo(qa_client, alice, check=False)
    path = f"{API}/studies/{journey.study.id}/population-studies"
    expect_error(await qa_client.post(path, json={"population_size": 121}, headers=alice), 409, "CONFLICT")  # demo cap 120
    for size in (19, 2001):
        expect_error(await qa_client.post(path, json={"population_size": size}, headers=alice), 422, "VALIDATION_ERROR")
    runs = parse(RunPage, await qa_client.get(f"{API}/projects/{journey.project_id}/runs", headers=alice))
    assert runs.total == 0, "refused studies must not start runs"


# --------------------------------------------------------------------------- follow-ups and memory


@needs(*STUDY_ROUTES, R.get_participant, R.ask_participant, R.list_participant_questions, R.ask_group)
@needs_workflow("run_population_study", "answer_followup", "answer_group_question")
async def test_follow_up_questions_are_synthetic_and_remembered(qa_client: httpx.AsyncClient, alice: dict[str, str]) -> None:
    journey = await demo_with_evidence(qa_client, alice)
    _, result = await run_population_study(qa_client, alice, journey.study.id)
    interview = next(i for i in await all_interviews(qa_client, alice, result.id) if i.status == "completed")
    base = f"{API}/population-studies/{result.id}/participants/{interview.participant_id}"
    detail = parse(ParticipantDetail, await qa_client.get(base, headers=alice))
    assert detail.state.stance == interview.reaction and detail.state.stance_source == "interview"
    assert detail.state.interview_id == interview.id and len(detail.memories) <= 50
    assert any(m.kind == "interview" and m.ref_id == interview.id for m in detail.memories)
    answer = parse(FollowUpAnswer, await qa_client.post(f"{base}/questions", json={"question": "Would you buy it this season?"}, headers=alice), 201)
    assert answer.is_synthetic and answer.participant_id == interview.participant_id and answer.model_id is None
    assert set(answer.memory_refs) <= {m.ref_id for m in detail.memories}, "an answer may only draw on stored memories"
    assert interview.id in answer.memory_refs, "the answer draws on the stored interview"
    quoted = any(len(a.answer.strip()) >= 12 and a.answer.strip()[:12] in answer.answer for a in interview.answers)
    assert quoted, "a demo answer quotes the participant's stored interview (§14.9)"
    remembered = parse(ParticipantDetail, await qa_client.get(base, headers=alice))
    assert remembered.memories[0].kind == "follow_up" and remembered.memories[0].ref_id == answer.id, "follow-ups become memories"
    page = parse(FollowUpPage, await qa_client.get(f"{base}/questions", headers=alice))
    assert [a.id for a in page.items] == [answer.id]
    group = parse(
        GroupQuestionResult,
        await qa_client.post(
            f"{API}/population-studies/{result.id}/groups/{interview.group_id}/questions",
            json={"question": "What would make this clearer?", "sample_size": 3},
            headers=alice,
        ),
        201,
    )
    assert len(group.answers) == 3 and all(a.is_synthetic and a.group_id == interview.group_id for a in group.answers)
    check_distribution(group.stance, "group question")
    assert group.stance.denominator + group.stance.failed == 3 and group.sample_note.strip()


# --------------------------------------------------------------------------- social simulation


@needs(*STUDY_ROUTES, R.start_social_simulation, R.get_social_simulation, R.list_social_posts)
@SOCIAL_WORKFLOW
async def test_social_simulation_is_traceable(qa_client: httpx.AsyncClient, alice: dict[str, str]) -> None:
    journey = await demo_with_evidence(qa_client, alice)
    _, study = await run_population_study(qa_client, alice, journey.study.id)
    expect_error(
        await qa_client.post(f"{API}/social-simulations", json={"population_study_id": str(study.id), "rounds": 6}, headers=alice),
        422,
        "VALIDATION_ERROR",
    )
    accepted = await start_run(
        qa_client, alice, f"{API}/social-simulations", {"population_study_id": str(study.id), "rounds": 3}, "social_simulation"
    )
    run = await wait_for_run(qa_client, accepted.run_id, alice, timeout=180)
    assert run.status in ("completed", "partial") and run.result is not None, f"social simulation ended {run.status}"
    sim = parse(SocialSimulationResult, await qa_client.get(run.result.url, headers=alice))
    assert sim.mode == "demo" and sim.rounds_requested == 3 and sim.rounds_completed == len(sim.rounds) <= 5
    inv.check_demo_run_metadata(sim.run_metadata, run.id, "social_simulation")
    assert sim.disclosure.is_synthetic and not sim.disclosure.independent_human_sample
    labels = " ".join([sim.disclosure.description, *sim.limitations]).lower()
    assert "not a forecast" in labels, "results must say they are illustrative, not a forecast (§14.6)"

    posts = await fetch_all(qa_client, f"{API}/social-simulations/{sim.id}/posts", alice, SocialPostPage)
    interview_ids = {i.id for i in await all_interviews(qa_client, alice, study.id)}
    earlier: set[Any] = set()
    for round_index in range(1, sim.rounds_completed + 1):
        current = [p for p in posts if p.round_index == round_index]
        for post in current:
            assert post.is_synthetic and post.reason is not None and post.stance is not None
            unknown = set(post.seen_post_ids) - earlier - interview_ids
            assert not unknown, f"post {post.id} saw ids that are neither earlier posts nor interviews: {unknown}"
        summary = next(s for s in sim.rounds if s.round_index == round_index)
        changed = {p.participant_id for p in current if p.previous_stance is not None and p.previous_stance != p.stance}
        assert summary.shifts == len(changed), f"round {round_index}: shifts {summary.shifts} != {len(changed)} stored changes"
        check_distribution(summary.stance, f"round {round_index} stance")
        earlier |= {p.id for p in current}
    by_round = await fetch_all(qa_client, f"{API}/social-simulations/{sim.id}/posts", alice, SocialPostPage, round_index=1)
    assert by_round and all(p.round_index == 1 for p in by_round)


# --------------------------------------------------------------------------- graph views


@needs(*STUDY_ROUTES, R.get_audience_landscape, R.get_reaction_map, R.get_campaign_comparison)
@POPULATION_WORKFLOW
async def test_graph_views_come_from_stored_records(qa_client: httpx.AsyncClient, alice: dict[str, str]) -> None:
    journey = await demo_with_evidence(qa_client, alice)
    _, first = await run_population_study(qa_client, alice, journey.study.id)
    _, second = await run_population_study(qa_client, alice, journey.study.id, population_id=str(first.population_id))
    views = {
        "landscape": f"{API}/populations/{first.population_id}/landscape",
        "reaction map": f"{API}/population-studies/{first.id}/reaction-map",
    }
    for name, path in views.items():
        view = parse(GraphView, await qa_client.get(path, params={"limit": 300}, headers=alice))
        check_graph(view, demo=True, where=name)
        again = parse(GraphView, await qa_client.get(path, params={"limit": 300}, headers=alice))
        assert [n.id for n in again.nodes] == [n.id for n in view.nodes] and [e.id for e in again.edges] == [e.id for e in view.edges], (
            f"{name}: ids are not stable"
        )
        await check_node_resources(qa_client, alice, view, name)
        small = parse(GraphView, await qa_client.get(path, params={"limit": 10}, headers=alice))
        check_graph(small, demo=True, where=f"{name} limit 10", limit=10)
        assert small.truncated is (len(view.nodes) > 10)
    landscape = parse(GraphView, await qa_client.get(views["landscape"], headers=alice))
    for edge in landscape.edges:
        if edge.relation == "similar_to":
            assert edge.weight is not None and 0 <= edge.weight <= 1 and "cosine" in (edge.weight_definition or "").lower()
    comparison = parse(
        CampaignComparison,
        await qa_client.get(
            f"{API}/campaigns/{journey.campaign_id}/population-comparison",
            params={"population_id": str(first.population_id), "population_study_ids": [str(first.id), str(second.id)]},
            headers=alice,
        ),
    )
    assert comparison.consistent_population and comparison.consistent_protocol and comparison.variability_note.strip()
    check_graph(comparison.graph, demo=True, where="comparison")
    for row in comparison.results:
        check_distribution(row.distribution, f"comparison {row.population_study_id} {row.group_id}")


# --------------------------------------------------------------------------- isolation


@needs(*STUDY_ROUTES, R.get_population, R.list_participants, R.get_participant, R.ask_participant, R.get_audience_landscape)
@POPULATION_WORKFLOW
async def test_v3_resources_of_other_users_are_not_found(
    qa_client: httpx.AsyncClient, alice: dict[str, str], bob: dict[str, str]
) -> None:
    journey = await demo_with_evidence(qa_client, alice)
    run, result = await run_population_study(qa_client, alice, journey.study.id)
    participant = (await fetch_all(qa_client, f"{API}/populations/{result.population_id}/participants", alice, ParticipantPage))[0]
    group = result.by_group[0].group_id
    for path in (
        f"{API}/studies/{journey.study.id}/population-studies",
        f"{API}/population-studies/{result.id}",
        f"{API}/population-studies/{result.id}/interviews",
        f"{API}/projects/{journey.project_id}/populations",
        f"{API}/populations/{result.population_id}",
        f"{API}/populations/{result.population_id}/participants",
        f"{API}/populations/{result.population_id}/landscape",
        f"{API}/population-studies/{result.id}/reaction-map",
        f"{API}/population-studies/{result.id}/participants/{participant.id}",
        f"{API}/population-studies/{result.id}/participants/{participant.id}/questions",
        f"{API}/population-studies/{result.id}/groups/{group}/questions",
        f"{API}/population-studies/{result.id}/social-simulations",
    ):
        expect_error(await qa_client.get(path, headers=bob), 404, "NOT_FOUND")
    for path, body in (
        (f"{API}/studies/{journey.study.id}/population-studies", {"population_size": 20}),
        (f"{API}/social-simulations", {"population_study_id": str(result.id)}),
        (f"{API}/runs/{run.id}/cancel", None),
        (f"{API}/runs/{run.id}/resume", None),
    ):
        expect_error(await qa_client.post(path, json=body, headers=bob), 404, "NOT_FOUND")
