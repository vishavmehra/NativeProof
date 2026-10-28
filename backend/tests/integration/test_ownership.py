"""Cross-user isolation and reference validation (TR-006, NFR-001, D-012, D-030, README §3/§4).

Another user's resources return 404, never 403 or 409, so their existence is not revealed. The caller's own
resource in the wrong place (other project/campaign, wrong run type, unfinished run) is 409 with a field detail.
Runs use the workflow double (`qa_fake`) so these checks do not depend on the workflows.
"""

from uuid import uuid4

import httpx

from app.schemas.projects import Project, ProjectPage
from app.schemas.runs import RunPage
from tests.integration._support import API, expect_error, parse
from tests.integration.journey import JAPAN, STUDY_REQUEST, create_demo, discover, full_journey


def assert_field(envelope, name: str) -> None:  # type: ignore[no-untyped-def]
    fields = [d.field for d in envelope.error.details]
    assert any(f and name in f for f in fields), f"expected a detail naming {name!r}, got {fields}"


async def test_other_users_resources_are_not_found(
    qa_client: httpx.AsyncClient, qa_fake: object, alice: dict[str, str], bob: dict[str, str]
) -> None:
    j = await full_journey(qa_client, alice, check=False)
    p, c, s = j.project_id, j.campaign_id, j.study.id  # type: ignore[union-attr]
    reads = [
        f"{API}/projects/{p}",
        f"{API}/projects/{p}/campaigns",
        f"{API}/campaigns/{c}",
        f"{API}/projects/{p}/discoveries/{j.discovery_run.id}",  # type: ignore[union-attr]
        f"{API}/projects/{p}/studies",
        f"{API}/studies/{s}",
        f"{API}/studies/{s}/rehearsals/{j.rehearsal_run.id}",  # type: ignore[union-attr]
        f"{API}/campaigns/{c}/adaptations",
        f"{API}/adaptations/{j.adaptations[0].id}",
        f"{API}/campaigns/{c}/evaluations/{j.evaluation.id}",  # type: ignore[union-attr]
        f"{API}/projects/{p}/evidence",
        f"{API}/evidence/{j.discovery.evidence[0].id}",  # type: ignore[union-attr]
        f"{API}/projects/{p}/reports",
        f"{API}/reports/{j.report.id}",  # type: ignore[union-attr]
        f"{API}/reports/{j.report.id}/export?format=json",  # type: ignore[union-attr]
        f"{API}/reports/{j.report.id}/export?format=markdown",  # type: ignore[union-attr]
        f"{API}/runs/{j.evaluation_run.id}",  # type: ignore[union-attr]
        f"{API}/projects/{p}/runs",
    ]
    for path in reads:
        expect_error(await qa_client.get(path, headers=bob), 404, "NOT_FOUND")
    writes = [
        ("PATCH", f"{API}/projects/{p}", {"name": "Taken over"}),
        ("DELETE", f"{API}/projects/{p}", None),
        ("POST", f"{API}/projects/{p}/campaigns", {"name": "X", "campaign_type": "slogan", "original_content": {"headline": "X"}}),
        ("PATCH", f"{API}/campaigns/{c}", {"name": "Taken over"}),
        ("POST", f"{API}/projects/{p}/discoveries", {"product_category": "x", "market": JAPAN, "research_question": "Why?"}),
        ("POST", f"{API}/projects/{p}/studies", {**STUDY_REQUEST, "campaign_id": str(c)}),
        ("POST", f"{API}/studies/{s}/rehearsals", {}),
        ("POST", f"{API}/campaigns/{c}/adaptations", {"market": JAPAN}),
        ("POST", f"{API}/adaptations/{j.adaptations[0].id}/revisions", {"content": {"headline": "Mine now"}}),
        (
            "POST",
            f"{API}/campaigns/{c}/evaluations",
            {
                "source_content_version_id": str(j.version_id),
                "candidate_adaptation_ids": [str(j.adaptations[0].id)],
                "market": JAPAN,
                "criteria": j.campaign.evaluation_criteria.model_dump(),
            },
        ),
        ("POST", f"{API}/projects/{p}/reports", {"campaign_id": str(c), "title": "Stolen"}),
    ]
    for method, path, body in writes:
        expect_error(await qa_client.request(method, path, json=body, headers=bob), 404, "NOT_FOUND")
    listed = parse(ProjectPage, await qa_client.get(f"{API}/projects", params={"include_archived": "true"}, headers=bob))
    assert p not in {item.id for item in listed.items}
    owner_view = parse(Project, await qa_client.get(f"{API}/projects/{p}", headers=alice))
    assert owner_view.status == "active" and owner_view.name == j.project.name, "bob's attempts changed alice's project"
    runs = parse(RunPage, await qa_client.get(f"{API}/projects/{p}/runs", headers=alice))
    assert runs.total == 4, "bob's attempts must not start runs in alice's project"


async def test_unknown_ids_are_not_found(qa_client: httpx.AsyncClient, alice: dict[str, str]) -> None:
    unknown = uuid4()
    for path in (
        f"{API}/projects/{unknown}",
        f"{API}/campaigns/{unknown}",
        f"{API}/studies/{unknown}",
        f"{API}/adaptations/{unknown}",
        f"{API}/evidence/{unknown}",
        f"{API}/reports/{unknown}",
        f"{API}/runs/{unknown}",
    ):
        expect_error(await qa_client.get(path, headers=alice), 404, "NOT_FOUND")
    journey = await create_demo(qa_client, alice)
    expect_error(
        await qa_client.get(f"{API}/projects/{journey.project_id}/discoveries/{unknown}", headers=alice), 404, "NOT_FOUND"
    )


async def test_cross_user_body_references_are_not_found(
    qa_client: httpx.AsyncClient, qa_fake: object, alice: dict[str, str], bob: dict[str, str]
) -> None:
    """D-030: referencing another user's run/adaptation/evaluation in a body → 404 (no existence leak)."""
    a = await full_journey(qa_client, alice, check=False)
    b = await create_demo(qa_client, bob)
    cases = [
        (f"{API}/studies/{b.study.id}/rehearsals", {"discovery_run_id": str(a.discovery_run.id)}, "discovery_run_id"),  # type: ignore[union-attr]
        (f"{API}/campaigns/{b.campaign_id}/adaptations", {"market": JAPAN, "rehearsal_run_id": str(a.rehearsal_run.id)}, "rehearsal_run_id"),  # type: ignore[union-attr]
        (
            f"{API}/campaigns/{b.campaign_id}/evaluations",
            {
                "source_content_version_id": str(b.version_id),
                "candidate_adaptation_ids": [str(a.adaptations[0].id)],
                "market": JAPAN,
                "criteria": b.campaign.evaluation_criteria.model_dump(),
            },
            "candidate_adaptation_ids",
        ),
        (f"{API}/projects/{b.project_id}/reports", {"campaign_id": str(b.campaign_id), "title": "Borrowed", "evaluation_id": str(a.evaluation.id)}, "evaluation_id"),  # type: ignore[union-attr]
    ]
    for path, body, field in cases:
        assert_field(expect_error(await qa_client.post(path, json=body, headers=bob), 404, "NOT_FOUND"), field)
    runs = parse(RunPage, await qa_client.get(f"{API}/projects/{b.project_id}/runs", headers=bob))
    assert runs.total == 0, "rejected requests must not start runs"


async def test_evaluation_candidates_must_match_campaign_and_version(
    qa_client: httpx.AsyncClient, qa_fake: object, alice: dict[str, str]
) -> None:
    """README §3 / D-030: the caller's candidate or version from another campaign is 409 CONFLICT."""
    first = await full_journey(qa_client, alice, check=False)
    second = await create_demo(qa_client, alice)
    criteria = first.campaign.evaluation_criteria.model_dump()

    def body(version: object) -> dict[str, object]:
        return {
            "source_content_version_id": str(version),
            "candidate_adaptation_ids": [str(first.adaptations[0].id)],
            "market": JAPAN,
            "criteria": criteria,
        }

    other_campaign = await qa_client.post(f"{API}/campaigns/{second.campaign_id}/evaluations", json=body(second.version_id), headers=alice)
    assert_field(expect_error(other_campaign, 409, "CONFLICT"), "candidate_adaptation_ids")
    wrong_version = await qa_client.post(f"{API}/campaigns/{first.campaign_id}/evaluations", json=body(second.version_id), headers=alice)
    assert_field(expect_error(wrong_version, 409, "CONFLICT"), "source_content_version_id")
    for journey, expected in ((first, 1), (second, 0)):
        runs = parse(
            RunPage,
            await qa_client.get(f"{API}/projects/{journey.project_id}/runs", params={"run_type": "campaign_evaluation"}, headers=alice),
        )
        assert runs.total == expected, "a rejected evaluation must not start a run"


async def test_same_user_run_references_are_validated(
    qa_client: httpx.AsyncClient, qa_fake: object, alice: dict[str, str]
) -> None:
    """D-030: another project's run, or a run of the wrong type, is 409 before any run starts."""
    first = await create_demo(qa_client, alice)
    await discover(qa_client, first, check=False)
    second = await create_demo(qa_client, alice)
    other_project = await qa_client.post(
        f"{API}/studies/{second.study.id}/rehearsals", json={"discovery_run_id": str(first.discovery_run.id)}, headers=alice  # type: ignore[union-attr]
    )
    assert_field(expect_error(other_project, 409, "CONFLICT"), "discovery_run_id")
    wrong_type = await qa_client.post(
        f"{API}/campaigns/{first.campaign_id}/adaptations",
        json={"market": JAPAN, "rehearsal_run_id": str(first.discovery_run.id)},  # type: ignore[union-attr]
        headers=alice,
    )
    assert_field(expect_error(wrong_type, 409, "CONFLICT"), "rehearsal_run_id")
    assert parse(RunPage, await qa_client.get(f"{API}/projects/{second.project_id}/runs", headers=alice)).total == 0
    assert parse(RunPage, await qa_client.get(f"{API}/projects/{first.project_id}/runs", headers=alice)).total == 1
