"""Demo-mode "model" outputs for the seeded Northstar / Japan scenario (contracts/README §5, contracts/fixtures).

Hand-written, deterministic, and labeled: the gateway records provider "fixture" and the workflows add
"Demo fixture output, not a live model response." Each responder receives the agent's structured input and
returns JSON in that agent's output schema, so validation and cross-reference checks run as in live mode.
Ratings and scores reproduce the contract story: clarity [4,3,2,4,2,3] -> 50.0, spread 0.82, disagreement;
overall 63.0 / 76.4 / 73.1 -> R4 accept.
"""

from collections.abc import Mapping
from typing import Any

from app.schemas.common import DIMENSIONS

Context = Mapping[str, Any]
SOURCE = ("Find your next great escape", "Built for the journeys that change you.", "Explore the collection")


def _join(names: list[str]) -> str:
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


def _source_handle(evidence: list[dict], prefer: str = "Hiking") -> str | None:
    sources = [e for e in evidence if e["evidence_type"] == "qloo_source" and e["claim_type"] == "observed"]
    preferred = [e for e in sources if prefer in (e.get("subject") or "", e.get("related") or "", e.get("title") or "")]
    return (preferred or sources or [{}])[0].get("handle")


# --- Atlas ------------------------------------------------------------------------------------


def atlas_brief(ctx: Context) -> dict:
    market = ctx["market"]["display_name"]
    refs = ctx["references"]
    resolved = [r for r in refs if r["status"] == "resolved"]
    seeds = [r for r in resolved if r["role"] != "related_interest"]
    related = [r for r in resolved if r["role"] == "related_interest"]
    unresolved = [r for r in refs if r["status"] == "unresolved" and r["role"] == "reference_term"]
    names = [r["name"] for r in resolved]
    observations = []
    for r in seeds:
        rel = [x for x in related if x.get("seed") == r["name"]]
        tail = f", with {_join([x['name'] for x in rel])} as a related interest" if rel else ""
        observations.append({
            "title": f"{r['name']} resolved as a relevant {r.get('entity_type') or 'entity'}",
            "explanation": f"'{r['query_term']}' resolved to {r['name']}{tail}.",
            "claim_type": "observed", "evidence": r["evidence"] + [h for x in rel for h in x["evidence"]],
        })
    opportunities = [{
        "title": f"Lead with {_join(names).lower()}-focused framing",
        "explanation": f"Framing the launch around {_join(names)} connects the copy to the supported signals.",
        "claim_type": "interpreted", "evidence": [h for r in resolved for h in r["evidence"]],
        "validation_question": f"Does copy framed around {_join(names).lower()} resonate with weekend hikers in {market}?",
    }] if names else []
    risks = [{
        "title": f"'{r['query_term']}' may not carry over",
        "explanation": f"The phrase did not resolve; its connotation in {market} is untested.",
        "claim_type": "hypothesis", "evidence": [],
        "validation_question": f"How do consumers in {market} read '{r['query_term']}' in an outdoor-apparel ad?",
    } for r in unresolved]
    summary = (f"{_join(names)} are the clearest supported signals for this launch." if names
               else "No reference resolved to a supported cultural signal.")
    if unresolved:
        summary += f" {_join([repr(r['query_term']) for r in unresolved])} did not resolve to any cultural reference and should be tested."
    notes = [{
        "reference": r["reference"],
        "relevance_explanation": (f"{r['name']} may extend the {r['seed']} theme toward related activities."
                                  if r["role"] == "related_interest"
                                  else f"{r['name']} matches the campaign's journey framing and the brand's outdoor positioning."),
    } for r in resolved]
    return {
        "summary": summary, "reference_notes": notes, "observations": observations, "opportunities": opportunities,
        "risks": risks, "validation_questions": [f["validation_question"] for f in risks],
        "limitations": ["Cultural affinity does not establish market demand."],
    }


# --- Audience -----------------------------------------------------------------------------------

SEGMENTS = [
    ("Weekend hikers", "Metropolitan professionals who hike one or two weekends a month."),
    ("Design-led urban buyers", "Style-conscious city residents who value minimal design."),
    ("Experienced mountaineers", "Technical climbers who judge gear on performance claims."),
    ("Gift buyers", "People choosing outdoor gear as a gift for a partner or family member."),
]

SENSITIVITY = {"severity": "medium", "category": "sensitivity",
               "description": "Escapism framing could read as dismissive of work commitments."}
# segment -> (sentiment, (clarity, brand_fidelity, cultural_relevance, cultural_risk), confusion, interpretation,
#             summary, confusions, risk flags)
REACTIONS: dict[str, list[tuple]] = {
    "Weekend hikers": [
        ("positive", (4, 4, 4, 2), 0.2, "An invitation to plan the next hiking trip with dependable gear.",
         "Feels aspirational and relevant to weekend trips.", [], []),
        ("neutral", (3, 4, 3, 2), 0.35, "Reads like a travel-agency slogan rather than an apparel message.",
         "Pleasant tone, but unclear what is being sold.", ["'Escape' suggests a holiday package, not clothing."], []),
    ],
    "Design-led urban buyers": [
        ("mixed", (2, 4, 2, 3), 0.6, "Suggests escaping from work and daily obligations.",
         "Stylish, but the escapism angle feels slightly off.",
         ["'Great escape' reads as leaving responsibilities behind."], [SENSITIVITY]),
        ("positive", (4, 5, 3, 1), 0.15, "A premium, understated brand promise.",
         "Minimal and confident; matches the brand.", [], []),
    ],
    "Experienced mountaineers": [
        ("negative", (2, 3, 2, 3), 0.55, "Generic travel copy with no performance claim.",
         "Says nothing about technical quality.", ["No product benefit is stated."],
         [{"severity": "low", "category": "ambiguity", "description": "No concrete product claim for technical buyers."}]),
        ("neutral", (3, 3, 3, 2), 0.3, "A lifestyle message aimed at casual hikers.",
         "Fine for beginners; not aimed at me.", [], []),
    ],
}
FIXTURE_REACTION_COUNT = sum(len(v) for v in REACTIONS.values())


def segments(ctx: Context) -> dict:
    return {"segments": [{"label": label, "description": text} for label, text in SEGMENTS[: ctx["count"]]]}


def reactions(ctx: Context) -> dict:
    label = ctx["segment_label"]
    table = ctx.get("_table", REACTIONS)
    canned = table.get(label) or list(table.values())[ctx["segment_index"] % len(table)]
    hiking = _source_handle(ctx["evidence"]) if label == "Weekend hikers" else None
    out = []
    for sentiment, ratings, confusion, interpretation, summary, confusions, flags in canned[ctx["offset"] :][: ctx["count"]]:
        scores = dict(zip(DIMENSIONS, ratings))
        out.append({
            "interpretation": interpretation, "reaction_summary": summary, "sentiment": sentiment,
            "ratings": {d: {"value": scores[d], "rationale": None} for d in ctx["dimensions"]},
            "confusion_level": confusion, "potential_confusions": confusions, "risk_flags": flags,
            "relevant_passage": ctx["content"]["headline"] if confusions else None,
            "evidence": [hiking] if hiking else [],
        })
    return {"reactions": out}


# --- Analyst ------------------------------------------------------------------------------------

_I = [r[3] for rows in REACTIONS.values() for r in rows]  # canned interpretations, contract order r0..r5


def analyst(ctx: Context) -> dict:
    rows = ctx["reactions"]

    def h(*indexes: int) -> list[str]:
        return [r["reaction"] for r in rows if r["interpretation"] in {_I[i] for i in indexes}]

    if not h(*range(len(_I))):
        return {"key_findings": [{
            "category": "other", "title": "Synthetic reactions to the campaign",
            "summary": "Demo fixtures have no analysis for these reactions.", "supporting_reactions": [r["reaction"] for r in rows],
            "evidence": [], "claim_type": "synthetic",
        }]}
    clarity = next((e["handle"] for e in ctx["evidence"] if e["evidence_type"] == "deterministic_calculation"
                    and e["title"].startswith("Clarity")), None)

    def f(category: str, title: str, summary: str, support: list[str], claim: str = "synthetic", evidence=()) -> dict:
        return {"category": category, "title": title, "summary": summary, "supporting_reactions": support,
                "evidence": [e for e in evidence if e], "claim_type": claim}

    return {
        "key_findings": [
            f("disagreement", "The headline splits interpretations",
              "Reactions diverged on what 'great escape' promises: gear for trips, a holiday, or leaving work.",
              h(0, 1, 2), evidence=[clarity]),
            f("brand_fidelity", "The brand voice lands", "Most reactions described the tone as minimal and confident.", h(0, 3)),
            f("cultural_relevance", "Technical buyers see no product claim",
              "Mountaineer perspectives found no concrete reason to choose the gear.", h(4, 5)),
        ],
        "potential_confusions": [
            f("confusion", "'Escape' read as travel or escapism",
              "Two reactions read the headline as a holiday offer or as leaving responsibilities.", h(1, 2)),
        ],
        "potential_cultural_risks": [
            f("cultural_risk", "Escapism may feel dismissive of work",
              "One reaction flagged the escapism framing as a possible sensitivity.", h(2), claim="hypothesis"),
        ],
        "disagreements": [{
            "topic": "What the headline promises", "dimension": "clarity",
            "interpretations": [
                {"label": "Gear for the next trip", "summary": "An invitation to plan outdoor trips.", "reactions": h(0, 3)},
                {"label": "A holiday or travel offer", "summary": "Reads as travel marketing.", "reactions": h(1, 4)},
                {"label": "Escaping obligations", "summary": "Reads as leaving work behind.", "reactions": h(2)},
            ],
            "possible_explanations": [
                "Hypothesis: 'escape' carries a 'leaving responsibilities' connotation for some readers.",
                "Hypothesis: the copy names no product, so readers fill the gap differently.",
            ],
            "validation_question": "Which reading of the headline do Japanese weekend hikers choose unprompted?",
        }],
        "validation_questions": [
            "Which reading of the headline do Japanese weekend hikers choose unprompted?",
            "Does naming a concrete product benefit change clarity for technical buyers?",
        ],
    }


# --- Voice, Red Team, Loop ------------------------------------------------------------------------

VARIANTS = [
    {"label": "Clearer message", "strategy": "Name the product and anchor the promise in trail use.",
     "headline": "Gear for the trails you keep coming back to",
     "body": "Built for the journeys that change you, from weekend ridgelines to alpine routes.",
     "call_to_action": "Explore the collection", "reference_terms": ["trails"],
     "changes": [("headline", "Replaces the ambiguous 'great escape' with trail framing supported by the Hiking signal.", True),
                 ("body", "Adds concrete terrain so technical buyers see a product context.", False)]},
    {"label": "Brand-first", "strategy": "Lead with the brand and replace escapism with a journey metaphor.",
     "headline": "Northstar. Built for the long way round.", "body": "Minimal gear for the journeys that change you.",
     "call_to_action": "Explore the collection", "reference_terms": [],
     "changes": [("headline", "Leads with the brand and swaps escapism for a journey metaphor.", False),
                 ("body", "Echoes the brand's minimal voice.", False)]},
    {"label": "More conservative", "strategy": "Keep the original structure and replace only the ambiguous phrase.",
     "headline": "Find your next trail", "body": "Built for the journeys that change you.",
     "call_to_action": "Explore the collection", "reference_terms": ["trail"],
     "changes": [("headline", "Replaces 'great escape', which reactions read as travel or escapism, with a concrete outdoor word.", False)]},
]
IDIOM = {"severity": "low", "category": "ambiguity",
         "description": "'The long way round' is an English idiom whose nuance may not carry over."}


def voice(ctx: Context) -> dict:
    hiking = _source_handle(ctx["evidence"])
    return {"variants": [
        {**{k: v for k, v in variant.items() if k != "changes"},
         "changes": [{"field": field, "reason": reason, "evidence": [hiking] if cites and hiking else []}
                     for field, reason, cites in variant["changes"]]}
        for variant in VARIANTS[: ctx["variant_count"]]
    ]}


def redteam(ctx: Context) -> dict:
    return {"reviews": [
        {"adaptation": a["adaptation"], "risks": [IDIOM] if "long way round" in (a["content"]["headline"] or "") else []}
        for a in ctx["adaptations"]
    ]}


def _key(content: Mapping[str, Any]) -> tuple:
    return (content.get("headline"), content.get("body"), content.get("call_to_action"))


# (clarity, brand_fidelity, cultural_relevance, cultural_risk), rationales, strengths, weaknesses, risks, cites evidence
ASSESSMENTS: dict[tuple, tuple] = {
    SOURCE: ((55, 84, 50, 30),
             ("'Great escape' is open to several readings.", "Confident and minimal, on brand.",
              "No reference resolved to a supported local signal.", "Escapism framing may read as dismissive of work."),
             ["Distinctive, confident tone"], ["No product benefit stated", "Ambiguous headline"], [SENSITIVITY], False),
    _key(VARIANTS[0]): ((78, 80, 70, 20),
                        ("States the product and use.", "Slightly less distinctive.", "Anchored in the Hiking signal.",
                         "No sensitivity found."),
                        ["Clear product category", "Trail framing supported by the Hiking signal"],
                        ["Less distinctive than the original"], [], True),
    _key(VARIANTS[1]): ((70, 92, 58, 22),
                        ("Clear, but the idiom adds ambiguity.", "Strongest brand presence.",
                         "No supported local reference.", "Idiom may not carry over."),
                        ["Strongest brand presence"], ["Idiom may not translate"], [], False),
    _key(VARIANTS[2]): ((66, 80, 62, 24),
                        ("Short and concrete, though it names no product.", "Keeps the original voice.",
                         "Trail wording is closer to the supported signals.", "Little room for misreading."),
                        ["Minimal change from the original"], ["Still names no product benefit"], [], False),
}


def judge(ctx: Context) -> dict:
    """Only fixture texts have scores; edited text gets no assessment (null scores, R0 inconclusive)."""
    hiking = _source_handle(ctx["evidence"])
    out = []
    for c in ctx["candidates"]:
        known = ASSESSMENTS.get(_key(c["content"]))
        if known is None:
            continue
        scores, rationales, strengths, weaknesses, risks, cites = known
        out.append({
            "candidate": c["candidate"],
            **{d: {"score": s, "rationale": r} for d, s, r in zip(DIMENSIONS, scores, rationales)},
            "strengths": strengths, "weaknesses": weaknesses, "risk_flags": risks,
            "evidence": [hiking] if cites and hiking else [],
        })
    return {"assessments": out}


RESPONDERS = {
    "atlas-brief-v2": atlas_brief,
    "audience-segments-v1": segments,
    "audience-reactions-v1": reactions,
    "analyst-v1": analyst,
    "voice-adaptations-v1": voice,
    "redteam-v1": redteam,
    "loop-judge-v1": judge,
}


# --- Contract v2 (contracts/README §13): fixture content only; anything else returns None (an honest gap) ---------

VARIANT_REACTIONS: dict[str, dict[str, list[tuple]]] = {
    "Clearer message": {
        "Weekend hikers": [
            ("positive", (5, 4, 5, 1), 0.05, "Gear made for the trails I already hike.", "Clear and relevant to my weekends.", [], []),
            ("positive", (4, 4, 4, 2), 0.15, "A practical promise about trail gear.", "Straightforward; I know what is on offer.", [], []),
        ],
        "Design-led urban buyers": [
            ("neutral", (4, 4, 3, 1), 0.15, "Outdoor gear with a clean, confident tone.", "Clear, though less distinctive than before.", [], []),
            ("neutral", (4, 3, 3, 2), 0.2, "A functional message about trail equipment.", "Clear but a little plain for the brand.", [], []),
        ],
        "Experienced mountaineers": [
            ("positive", (4, 3, 4, 2), 0.15, "Gear framed around real terrain, from ridgelines to alpine routes.",
             "Finally says where the gear is used.", [], []),
            ("neutral", (3, 3, 4, 1), 0.25, "Trail gear for regular hikers more than climbers.", "Better, still light on performance detail.",
             ["No technical specification is given."], []),
        ],
    },
    "Brand-first": {
        "Weekend hikers": [
            ("neutral", (4, 5, 3, 2), 0.2, "A brand statement about taking the scenic route.", "Strong brand, vaguer about the product.", [], []),
            ("neutral", (3, 4, 3, 2), 0.35, "An invitation to slow, longer journeys.", "Nice idea, but the idiom feels foreign.",
             ["'The long way round' may not translate naturally."], [IDIOM]),
        ],
        "Design-led urban buyers": [
            ("positive", (4, 5, 4, 1), 0.1, "A confident, minimal brand promise.", "Feels premium and on brand.", [], []),
            ("positive", (4, 5, 3, 1), 0.15, "Northstar as a considered lifestyle choice.", "Elegant and understated.", [], []),
        ],
        "Experienced mountaineers": [
            ("negative", (3, 4, 2, 2), 0.4, "A slogan with no performance claim.", "Brand-forward but says little about gear.",
             ["No product benefit is stated."], []),
            ("negative", (2, 4, 2, 3), 0.55, "An English idiom about detours.", "Unclear what it means for climbing gear.",
             ["The idiom's meaning is unclear."], [IDIOM]),
        ],
    },
    "More conservative": {
        "Weekend hikers": [
            ("positive", (4, 4, 4, 1), 0.1, "An invitation to find a new trail.", "Simple and relevant.", [], []),
            ("neutral", (4, 4, 3, 2), 0.2, "Trail discovery, close to the original idea.", "Clear enough; feels familiar.", [], []),
        ],
        "Design-led urban buyers": [
            ("neutral", (3, 4, 3, 2), 0.3, "Outdoor discovery with a minimal tone.", "Fine, if a little generic.", [], []),
            ("neutral", (3, 4, 2, 2), 0.35, "A gentle prompt to go outside.", "Pleasant but not memorable.", [], []),
        ],
        "Experienced mountaineers": [
            ("neutral", (3, 3, 3, 2), 0.3, "A casual trail message.", "Not aimed at technical buyers.", ["No product benefit is stated."], []),
            ("neutral", (3, 3, 3, 2), 0.3, "Trail discovery for beginners.", "Fine for newcomers.", [], []),
        ],
    },
}
_BY_CONTENT = {SOURCE: REACTIONS, **{_key(v): VARIANT_REACTIONS[v["label"]] for v in VARIANTS}}


def arena_reactions(ctx: Context) -> dict | None:
    table = _BY_CONTENT.get(_key(ctx["content"]))
    return None if table is None else reactions({**ctx, "_table": table})


REVIEWS: dict[tuple, tuple] = {
    SOURCE: (["Distinctive, confident tone"], ["The headline reads as travel or escapism"],
             [("Name the product and a concrete use in the headline.", "Several synthetic reactions could not tell what was sold.", False)]),
    _key(VARIANTS[0]): (["Clear product and use", "Trail framing matches the Hiking signal"], ["Less distinctive than the original"],
                        [("Add one concrete performance detail for technical buyers.", "Mountaineer reactions still asked for specifications.", True)]),
    _key(VARIANTS[1]): (["Strongest brand presence"], ["The English idiom may not carry over"],
                        [("Replace 'the long way round' with a plain phrase about longer journeys.", "Reactions flagged the idiom as unclear.", False)]),
    _key(VARIANTS[2]): (["Minimal change from the original"], ["Still names no product benefit"],
                        [("State what the collection is for.", "Reactions found the copy pleasant but generic.", False)]),
}


def arena_review(ctx: Context) -> dict:
    hiking = _source_handle(ctx["evidence"])
    reviews = []
    for v in ctx["variants"]:
        known = REVIEWS.get(_key(v["content"]))
        if known:
            strengths, weaknesses, improvements = known
            reviews.append({"variant": v["variant"], "strengths": strengths, "weaknesses": weaknesses, "improvements": [
                {"suggestion": s, "rationale": r, "evidence": [hiking] if cites and hiking else []} for s, r, cites in improvements]})
    return {"reviews": reviews}


RISKS: dict[tuple, list[dict]] = {
    SOURCE: [
        {"field": "headline", "excerpt": "great escape", "category": "ambiguity", "severity": "medium",
         "interpretation": "'Great escape' can read as a holiday offer or as leaving work behind, so the product is unclear.",
         "suggested_alternative": "next trail"},
        {"field": "headline", "excerpt": "escape", "category": "sensitivity", "severity": "low",
         "interpretation": "Escapism framing could read as dismissive of work commitments.", "suggested_alternative": "trail"},
        {"field": "body", "excerpt": "journeys that change you", "category": "unsupported_claim", "severity": "low",
         "interpretation": "A transformative promise with no concrete product benefit.", "suggested_alternative": "journeys you plan for"},
    ],
    _key(VARIANTS[0]): [],
    _key(VARIANTS[1]): [{"field": "headline", "excerpt": "the long way round", "category": "ambiguity", "severity": "low",
                         "interpretation": "An English idiom whose nuance may not carry over in Japan.",
                         "suggested_alternative": "every longer journey"}],
    _key(VARIANTS[2]): [],
}


def risk_scan(ctx: Context) -> dict | None:
    findings = RISKS.get(_key(ctx["content"]))
    return None if findings is None else {"findings": findings}


def cultural_profile(ctx: Context) -> dict:
    rows = [e for e in ctx["evidence"] if e["evidence_type"] == "qloo_source"]
    items, names = [], []
    for e in rows:
        if e.get("related"):
            items.append({"kind": "association", "title": f"{e['related']} is associated with {e['subject']}",
                          "explanation": f"Qloo returned {e['related']} as a related interest for {e['subject']}.",
                          "claim_type": "observed", "market": e["market"], "evidence": [e["handle"]]})
            names.append(e["related"])
        elif e.get("subject"):
            items.append({"kind": "affinity", "title": f"{e['subject']} is a supported signal",
                          "explanation": f"Discovery resolved {e['subject']} as a relevant signal.",
                          "claim_type": "observed", "market": e["market"], "evidence": [e["handle"]]})
            names.append(e["subject"])
    names = list(dict.fromkeys(names))
    if names:
        items.append({"kind": "opportunity", "title": f"Lead with {_join(names).lower()}",
                      "explanation": f"Framing the brand around {_join(names)} connects it to the supported signals.",
                      "claim_type": "interpreted", "market": None, "evidence": [e["handle"] for e in rows]})
    items.append({"kind": "conflict", "title": "Escapism framing is untested",
                  "explanation": "Campaign phrases without a Qloo match need validation with real people before launch.",
                  "claim_type": "hypothesis", "market": None, "evidence": []})
    markets = ", ".join(m["display_name"] for m in ctx["markets"])
    context = [f"{m['display_name']}: {sum(e['market'] == m['country_code'] for e in rows)} supporting Qloo records."
               for m in ctx["markets"]]
    return {"summary": f"{_join(names) if names else 'No signal'} anchors the {ctx['subject']} profile in {markets}.",
            "items": items, "market_context": context, "missing_evidence": []}


def market_summary(ctx: Context) -> dict:
    columns = ctx["columns"]
    signals = _join(list(dict.fromkeys(s for c in columns for s in c["signals"])))
    note = "" if ctx["market_specific_signals"] else " The signals do not differ by market, so they cannot rank markets."
    return {
        "cross_market_summary": f"Only {', '.join(c['market'] for c in columns)} has usable Qloo signals ({signals}).{note}",
        "markets": [{"market": c["market"], "claim_type": "interpreted",
                     "assessment": f"{_join(c['signals'])} fit the brand's outdoor positioning; confirm with local research."}
                    for c in columns],
    }


RESPONDERS |= {
    "arena-reactions-v1": arena_reactions,
    "arena-review-v1": arena_review,
    "risk-scan-v2": risk_scan,
    "cultural-profile-v1": cultural_profile,
    "market-summary-v1": market_summary,
}

from app.fixtures.demo_population import RESPONDERS as POPULATION_RESPONDERS  # noqa: E402

RESPONDERS |= POPULATION_RESPONDERS
