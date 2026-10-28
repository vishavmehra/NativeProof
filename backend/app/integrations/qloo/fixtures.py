"""Hand-authored demo fixtures in the `qloo exec` result-envelope format (D-019).

Nothing here was retrieved from Qloo. Ids carry the `fixture:` prefix, values are
illustrative, and the service labels every result fixture / hand_authored. Replace these
with sanitized live captures (fixture_origin "captured_live") once a credential exists.
Consistent with contracts/fixtures/DiscoveryResult.json (Northstar, Japan).
"""

from datetime import UTC, datetime
from typing import Any

from app.integrations.qloo.executor import RESULT_SCHEMA_VERSION, Envelope, QlooError, QlooFailure

FIXTURE_ID_PREFIX = "fixture:"
FIXTURE_TIMESTAMP = datetime(2026, 10, 25, tzinfo=UTC)  # when these fixtures were authored
FIXTURE_LIMITATION = "Demo fixture: hand-authored in the Qloo result format, not retrieved from Qloo."
FIXTURE_VALUE_DESCRIPTION = (
    "Illustrative fixture value. The live adapter preserves Qloo's own field meaning; not a probability."
)
NO_FIXTURE = "No demo fixture for this term."  # contracts/README §5


def _tag(slug: str, name: str) -> dict[str, Any]:
    return {"id": f"{FIXTURE_ID_PREFIX}tag:{slug}", "name": name, "type": "tag"}


HIKING = _tag("hiking", "Hiking")
CAMPING = _tag("camping", "Camping")
TRAIL_RUNNING = _tag("trail-running", "Trail running")
MINIMALISM = _tag("minimalism", "Minimalism")
MINIMALIST_ARCHITECTURE = _tag("minimalist-architecture", "Minimalist architecture")
MOUNTAINEERING = _tag("mountaineering", "Mountaineering")

# find_tags results by normalized query. The service's near-exact rule decides the outcome, as
# in live mode: "hiking" resolves; "outdoor exploration" and "minimal design" are ambiguous
# because no top candidate is named like the term; "great escape" has no candidates.
# "minimalism" and "mountaineering" ground the seeded population's other segments (design-led buyers, mountaineers).
FIND_TAGS: dict[str, list[dict[str, Any]]] = {
    "outdoor exploration": [HIKING, TRAIL_RUNNING],
    "hiking": [HIKING],
    "camping": [CAMPING],
    "trail running": [TRAIL_RUNNING],
    "minimal design": [MINIMALISM, MINIMALIST_ARCHITECTURE],
    "great escape": [],
    "minimalism": [MINIMALISM],
    "mountaineering": [MOUNTAINEERING],
}

# recommend results by seed id. recommend returns entities (never tags), so the demo uses fictional brands.
KUMO_TRAIL = {"entity_id": f"{FIXTURE_ID_PREFIX}brand:kumo-trail", "name": "Kumo Trail Co. (fictional)", "type": "brand"}
SHIZUKA = {"entity_id": f"{FIXTURE_ID_PREFIX}brand:shizuka-living", "name": "Shizuka Living (fictional)", "type": "brand"}
TAKANE = {"entity_id": f"{FIXTURE_ID_PREFIX}brand:takane-alpine", "name": "Takane Alpine Works (fictional)", "type": "brand"}
RECOMMEND: dict[str, list[dict[str, Any]]] = {
    HIKING["id"]: [{**KUMO_TRAIL, "affinity": 0.71}],
    MINIMALISM["id"]: [{**SHIZUKA, "affinity": 0.64}],
    MOUNTAINEERING["id"]: [{**TAKANE, "affinity": 0.58}, {**KUMO_TRAIL, "affinity": 0.52}],
}


def _envelope(workflow: str, status: str, results: list[dict[str, Any]], summary: str | None = None) -> Envelope:
    return Envelope.model_validate(
        {
            "schema_version": RESULT_SCHEMA_VERSION,
            "operation": workflow,
            "status": status,
            "summary": summary,
            "results": results,
            "result_count": len(results),
            "execution": {
                "transport": "fixture",
                "transport_name": "Nativeproof demo fixtures (hand-authored)",
                "correlation_id": "fixture",
                "duration_ms": 0,
            },
        }
    )


class FixtureExecutor:
    """Demo executor: deterministic, never calls Qloo, needs no credential.

    Demographics and trends have no fixtures on purpose: invented demographic scores or popularity series
    could pass for real data, so demo projects get an empty result with NO_FIXTURE instead.
    """

    transport = "fixture"

    def is_configured(self) -> bool:
        return True

    async def run(self, workflow: str, request: dict[str, Any]) -> Envelope:
        if workflow == "find_tags":
            results = FIND_TAGS.get(request["query"].lower())
        elif workflow == "recommend":
            seeds = request.get("include_tags") or request.get("signal_tags") or request.get("signals") or []
            results = RECOMMEND.get(seeds[0]) if seeds else None
        elif workflow == "search_entities":
            results = []  # the demo scenario has no entity fixtures; tag fixtures decide every outcome
        elif workflow in ("audience_demographics", "trends"):
            results = None
        else:
            raise QlooFailure(
                QlooError(code="QLOO_WORKFLOW_UNAVAILABLE", message="No demo fixture for this workflow.", retryable=False)
            )
        if results is None:
            return _envelope(workflow, "empty", [], NO_FIXTURE)
        return _envelope(workflow, "ok", results[: request.get("limit", 10)])
