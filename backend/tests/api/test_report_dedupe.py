"""Report bodies state each limitation and next step once (real demo workflows, no network)."""

import collections
from typing import Any

import httpx

from app.services.reports import _norm
from tests.api.test_demo_journey import offline  # noqa: F401  (fixture: blocks outbound HTTP and subprocesses)
from tests.api.test_v2_runs import JAPAN, finish

API = "/api/v1"


async def test_report_body_has_no_duplicated_limitations_or_steps(client: httpx.AsyncClient, offline: Any) -> None:
    project = (await client.post(f"{API}/projects/demo")).json()
    pid = project["id"]
    campaign = (await client.get(f"{API}/projects/{pid}/campaigns")).json()["items"][0]
    study = (await client.get(f"{API}/projects/{pid}/studies")).json()["items"][0]
    discovery = await finish(client, f"{API}/projects/{pid}/discoveries", {
        "campaign_id": campaign["id"], "product_category": "outdoor apparel", "market": JAPAN,
        "research_question": "Which interests matter?", "reference_terms": ["hiking", "great escape"]})
    rehearsal = await finish(client, f"{API}/studies/{study['id']}/rehearsals", {"discovery_run_id": discovery["id"]})
    adaptation = await finish(client, f"{API}/campaigns/{campaign['id']}/adaptations", {
        "market": JAPAN, "discovery_run_id": discovery["id"], "rehearsal_run_id": rehearsal["id"]})
    evaluation = await finish(client, f"{API}/campaigns/{campaign['id']}/evaluations", {
        "source_content_version_id": campaign["current_version"]["id"], "market": JAPAN,
        "candidate_adaptation_ids": adaptation["result"]["ids"], "criteria": campaign["evaluation_criteria"]})
    report = (await client.post(f"{API}/projects/{pid}/reports", json={
        "campaign_id": campaign["id"], "title": "Dedupe", "discovery_run_id": discovery["id"],
        "rehearsal_run_id": rehearsal["id"], "adaptation_ids": adaptation["result"]["ids"],
        "evaluation_id": evaluation["result"]["ids"][0]})).json()

    normalized = [_norm(x) for x in report["limitations"]]
    assert len(normalized) == len(set(normalized))
    assert not set(report["executive_summary"]["next_steps"]) & set(report["validation_steps"])
    per_adaptation = [x for a in report["adaptations"] for x in a["limitations"]]
    shared = [x for x in report["adaptations"][0]["limitations"] if per_adaptation.count(x) == len(report["adaptations"])]
    assert len(report["adaptations"]) > 1 and shared, "the demo variants share a limitation; the test needs one"

    markdown = (await client.get(f"{API}/reports/{report['id']}/export")).text
    narrative = [line for line in markdown.splitlines() if line.startswith("- ") and not line.startswith(
        ("- **", "- Protected terms", "- Prohibited terms", "- Change to", "- Warning", "- Run "))]
    repeated = [line for line, count in collections.Counter(narrative).items() if count > 1]
    assert repeated == []
    for limitation in shared:
        assert markdown.count(limitation) == 1  # once, under Limitations, not once per adaptation
