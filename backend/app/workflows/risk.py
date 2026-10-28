"""Cultural Risk Radar: deterministic brand checks, model text risks with exact excerpts, and vision observations.

Observation (exact text or a visible element) stays separate from interpretation. Excerpts are verified in code;
a finding whose excerpt or observation cannot be found is dropped. Findings start `open`.
"""

import re
import time
from typing import TypedDict
from uuid import uuid4

from langchain_core.runnables import RunnableConfig

from app.agents import creative
from app.agents._common import DEMO_OUTPUT_NOTE, DROPPED_NOTE, content_dict, evidence_digest, pick
from app.agents.brand import applied_note, brand_block
from app.analytics import is_source_observed
from app.llm.gateway import LLMError
from app.schemas.assets import VisionStatus, VisualObservation
from app.schemas.common import StepTrace
from app.schemas.evidence import EvidenceRecord
from app.schemas.risk import RiskFinding, TextLocation
from app.schemas.runs import RunError
from app.workflows._common import (
    DEMO_RUN_NOTE,
    STAGES,
    announce,
    execute,
    linear_graph,
    llm_error,
    local_step,
    merge_steps,
    observe_assets,
    outcome_status,
    utcnow,
)
from app.workflows.types import ProgressFn, RiskScanInput, RiskScanOutcome, WorkflowDeps

RUN = "risk_scan"
S1, S2, S3, S4 = STAGES[RUN]
FIELDS = ("headline", "body", "call_to_action")
MODEL_NOTE = "Model interpretation for human review; not a verified violation."
CUSTOM_TEXT_NOTE = "Demo fixtures cannot assess custom text; only deterministic brand checks ran."


class State(TypedDict, total=False):
    inp: RiskScanInput
    findings: list[RiskFinding]
    observations: list[VisualObservation]
    vision: VisionStatus
    brand_text: str
    applied: list[str]
    draft: list
    handles: dict[str, EvidenceRecord]
    limitations: list[str]
    steps: list[StepTrace]
    error: RunError | None
    stop: bool
    partial: bool


_WORD = re.compile(r"[\w'’-]+")


def fit_alternative(text: str, start: int, end: int, alternative: str | None) -> str | None:
    """Trim words the model repeated from just before or after the excerpt, so that applying the alternative replaces
    exactly the excerpt span ("Find your next great escape" + "next trail" must give "Find your next trail")."""
    if not alternative or not alternative.strip():
        return None
    words = alternative.split()
    def key(word: str) -> str:
        return word.strip(".,;:!?\"'“”‘’()").casefold()

    before, after = _WORD.findall(text[:start]), _WORD.findall(text[end:])
    for k in range(min(len(before), len(words) - 1), 0, -1):
        if [key(w) for w in words[:k]] == [key(w) for w in before[-k:]]:
            words = words[k:]
            break
    for k in range(min(len(after), len(words) - 1), 0, -1):
        if [key(w) for w in words[-k:]] == [key(w) for w in after[:k]]:
            words = words[:-k]
            break
    return " ".join(words)


def _locate(text: str | None, excerpt: str) -> tuple[int, int] | None:
    if not text or not excerpt:
        return None
    start = text.find(excerpt)
    if start < 0:
        match = re.search(re.escape(excerpt), text, flags=re.IGNORECASE)
        start = match.start() if match else -1
    return (start, start + len(excerpt)) if start >= 0 else None


async def loading_content(state: State, config: RunnableConfig) -> dict:
    await announce(config, RUN, 0, "Loading content and running brand checks.")
    started, inp, now = time.perf_counter(), state["inp"], utcnow()
    text, applied = brand_block(inp.context.brand)
    findings = []
    for term in inp.context.brand.prohibited_terms:
        for field in FIELDS:
            value = getattr(inp.content, field)
            span = _locate(value, term)
            if span:
                findings.append(RiskFinding(
                    id=uuid4(), category="constraint_violation", severity="high", confidence_label="moderate",
                    source="deterministic_check",
                    text_location=TextLocation(field=field, excerpt=value[span[0]:span[1]], start=span[0], end=span[1]),
                    visual_observation_id=None, observation=value[span[0]:span[1]],
                    interpretation="Brand Memory prohibits this term (deterministic, case-insensitive check).",
                    brand_rule=f"Prohibited term: {term}", evidence_ids=[], limitations=[], suggested_alternative=None,
                    status="open", status_note=None, updated_at=now,
                ))
    return {"findings": findings, "brand_text": text, "applied": applied,
            "steps": [local_step(S1, "red_team", "nativeproof", started)]}


async def analyzing_creatives(state: State, config: RunnableConfig) -> dict:
    await announce(config, RUN, 1, "Analyzing creatives.")
    started, deps, inp = time.perf_counter(), config["configurable"]["deps"], state["inp"]
    vision, by_asset, traces = await observe_assets(
        deps, [(str(a.asset_id), a) for a in inp.assets], config["configurable"]["mode"], S2)
    step = merge_steps(S2, "vision", traces, started) if traces else local_step(S2, "vision", None, started, status="skipped")
    notes = [f"Vision: {vision.message}"] if vision.message else []
    return {"vision": vision, "observations": [o for rows in by_asset.values() for o in rows],
            "steps": [*state["steps"], step], "limitations": [*state.get("limitations", []), *notes]}


async def assessing_risks(state: State, config: RunnableConfig) -> dict:
    await announce(config, RUN, 2, "Assessing cultural risks.")
    deps, inp = config["configurable"]["deps"], state["inp"]
    digest, handles = evidence_digest(inp.grounding_evidence, sources_only=True)
    observations = [{"id": o.id, "kind": o.kind, "description": o.description} for o in state["observations"]]
    try:
        result = await creative.assess_risks(
            deps.llm, stage=S3, content=content_dict(inp.content), market=inp.market.display_name,
            brand=state["brand_text"], observations=observations, evidence=digest,
        )
    except LLMError as exc:
        if deps.llm.is_fixture:
            return {"draft": [], "handles": handles, "steps": [*state["steps"], exc.trace], "partial": True,
                    "limitations": [*state.get("limitations", []), CUSTOM_TEXT_NOTE]}
        return {"draft": [], "handles": handles, "steps": [*state["steps"], exc.trace], "partial": True,
                "error": llm_error(exc, S3, "Deterministic brand checks and visual observations were saved.")}
    return {"draft": result.value.findings, "handles": handles, "steps": [*state["steps"], result.trace]}


async def checking_evidence(state: State, config: RunnableConfig) -> dict:
    await announce(config, RUN, 3, "Checking excerpts and evidence.")
    started, inp, now = time.perf_counter(), state["inp"], utcnow()
    observations = {o.id: o for o in state["observations"]}
    rules = {r.casefold(): r for r in state["applied"]}
    demo = [DEMO_OUTPUT_NOTE] if config["configurable"]["mode"] == "demo" else []
    findings, dropped, invalid = list(state["findings"]), 0, 0
    for item in state.get("draft", []):
        location, observed, observation_id, alternative = None, None, None, None
        if item.field and item.excerpt:
            value = getattr(inp.content, item.field)
            span = _locate(value, item.excerpt)
            if span:
                observed = value[span[0]:span[1]]
                alternative = fit_alternative(value, span[0], span[1], item.suggested_alternative)
                location = TextLocation(field=item.field, excerpt=observed, start=span[0], end=span[1])
        elif item.visual_observation and item.visual_observation in observations:
            observation_id = item.visual_observation
            observed = observations[observation_id].description
        if observed is None:  # the model quoted text or an element that is not there: invalid, never saved
            invalid += 1
            continue
        cited, lost = pick(item.evidence, state.get("handles", {}))
        dropped += lost
        findings.append(RiskFinding(
            id=uuid4(), category=item.category, severity=item.severity,
            confidence_label="moderate" if any(is_source_observed(e) for e in cited) else "limited",
            source="model_assessment", text_location=location, visual_observation_id=observation_id,
            observation=observed, interpretation=item.interpretation,
            brand_rule=rules.get((item.brand_rule or "").casefold()), evidence_ids=[e.id for e in cited],
            limitations=[MODEL_NOTE, *demo], suggested_alternative=alternative,
            status="open", status_note=None, updated_at=now,
        ))
    notes = [*state.get("limitations", []), *([DROPPED_NOTE] if dropped else [])]
    update = {"findings": findings, "limitations": notes, "steps": [*state["steps"], local_step(S4, "red_team", "nativeproof", started)]}
    if invalid:  # defect #5: explicit error instead of silently persisting part of the model output
        update |= {"partial": True, "error": state.get("error") or RunError(
            code="RUN_FAILED", stage=S4, retryable=True,
            message=f"{invalid} model finding(s) quoted text or elements that are not in the campaign and were not saved.")}
    return update


GRAPH = linear_graph(State, [(S1, loading_content), (S2, analyzing_creatives), (S3, assessing_risks), (S4, checking_evidence)])


async def run_risk_scan(inp: RiskScanInput, deps: WorkflowDeps, progress: ProgressFn | None = None) -> RiskScanOutcome:
    state = await execute(GRAPH, {"inp": inp, "steps": [], "limitations": []}, deps, progress, inp.context.mode)
    applied = state.get("applied", [])
    demo = [DEMO_RUN_NOTE] if inp.context.mode == "demo" else []
    return RiskScanOutcome(
        status=outcome_status(state), findings=state.get("findings", []), visual_observations=state.get("observations", []),
        vision=state.get("vision") or VisionStatus(status="not_requested", provider=None, model_id=None, message=None),
        evidence=[], brand_rules_applied=applied,
        limitations=list(dict.fromkeys([*demo, *state.get("limitations", []), applied_note(applied)])),
        steps=state.get("steps", []), error=state.get("error"),
    )
