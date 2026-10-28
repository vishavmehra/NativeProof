"""Demo "model" outputs for population studies and social simulation (contracts/README §14.8).

Deterministic and labeled: answers are chosen from fixed pools by participant ordinal, so the seeded population always
gets the same answers. Groups use only the demo evidence handles they are given. No provider is called.
"""

from collections import Counter
from collections.abc import Mapping
from typing import Any

Context = Mapping[str, Any]

GROUPS = [
    ("Weekend trail seekers", "Plan hikes to reset from city routines and value dependable gear."),
    ("Design-led city commuters", "Choose outdoor pieces that also work in the city and favor minimal looks."),
    ("Technical mountaineers", "Judge gear by performance claims and specifications."),
    ("Gift-minded planners", "Buy outdoor gear as thoughtful gifts and look for clear product benefits."),
    ("Comfort-first campers", "Prefer easy, comfortable trips and practical kit."),
    ("Eco-conscious minimalists", "Buy fewer, longer-lasting products and question marketing claims."),
    ("Spontaneous day-trippers", "Head out on short notice and respond to inspiring imagery."),
    ("Gear reviewers", "Compare products in detail before buying and share opinions online."),
    ("Seasonal leaf-peepers", "Time trips around autumn colors and seasonal events."),
    ("Urban wellness walkers", "Walk and hike for a mental reset."),
    ("Craft-first buyers", "Pay for craft and durability and are skeptical of hype."),
    ("Photo-first explorers", "Choose routes and gear for the pictures they will take."),
]
POOLS = {
    "Weekend trail seekers": ["positive", "positive", "mixed", "positive", "neutral"],
    "Design-led city commuters": ["mixed", "positive", "neutral", "confused", "mixed"],
    "Technical mountaineers": ["negative", "neutral", "mixed", "negative", "confused"],
}
DEFAULT_POOL = ["neutral", "mixed", "positive", "negative", "confused"]
LINES = {
    "positive": ("makes me want to plan my next autumn hike.", "Gear for the trips I already take.", "Very relevant to my weekends.",
                 "The confident, minimal tone.", "Nothing is confusing.", "Mostly; it promises little it cannot keep.",
                 "No real concerns.", "Show the gear on a real trail."),
    "mixed": ("is stylish, but the escape idea feels a bit off.", "Something about getting away, maybe from work.",
              "Partly relevant.", "The look and the brand.", "Escape from what, exactly?", "Somewhat.",
              "It sounds like leaving responsibilities behind.", "Say what the product is for."),
    "neutral": ("is pleasant but generic.", "An outdoor brand inviting me outside.", "Not especially relevant.",
                "Nothing stands out.", "Not really.", "Neutral; it makes no claim.", "None.", "Give me a concrete reason to care."),
    "negative": ("says nothing about how the gear performs.", "A lifestyle slogan.", "Not relevant to how I choose gear.",
                 "Nothing.", "What is being sold?", "No: there is no claim to trust.", "No performance information.",
                 "Name the materials and what they handle."),
    "confused": ("reads like a travel offer.", "Maybe a holiday package?", "Unclear.", "The image of travel.",
                 "Is this clothing or a trip?", "I cannot tell yet.", "I might expect a trip, not gear.", "Show the product."),
}
THEMES = {"positive": ["trail inspiration", "brand tone"], "mixed": ["escapism", "brand tone"], "neutral": ["generic message"],
          "negative": ["no product benefit", "escapism"], "confused": ["unclear product", "travel offer"]}
CONCERNS = {"mixed": ["work-life framing"], "negative": ["no performance claim"], "confused": ["what is being sold"]}
FOLLOW_UPS = [("What would make the product clearer?", "Naming the gear and one thing it does well."),
              ("Would you share it with friends?", "Only if it showed a real trail.")]
QUESTIONS = ("first_impression", "comprehension", "relevance", "appeal", "confusion", "trust", "concerns", "improvement")
POSTS = {"positive": "Looks like solid gear for autumn trails.", "mixed": "Nice tone, but I'm still not sure what's on offer.",
         "negative": "Still no reason to pick this gear.", "neutral": "Seen it; nothing new for me.",
         "confused": "Is this a travel offer or a clothing ad?"}


def groups(ctx: Context) -> dict:
    regions = ctx["regions"]
    out = []
    for i in range(ctx["count"]):
        label, description = GROUPS[i % len(GROUPS)]
        code = regions[i % len(regions)]["country_code"]
        own = [x for x in ctx.get("interests", []) if x["region"] == code]  # the region's interests, best first
        held = list({x["handle"]: x for x in (own[i % len(own)], own[(i + 1) % len(own)])}.values()) if own else []
        out.append({"label": label, "description": description, "region": code, "share": round(1 / ctx["count"], 4),
                    "interests": [x["handle"] for x in held],
                    "evidence": list(dict.fromkeys(h for x in held for h in x["evidence"]))})
    return {"groups": out}


def interviews(ctx: Context) -> dict:
    headline = ctx["content"].get("headline") or ctx["content"].get("body") or "This campaign"
    follow_ups = {"brief": 0, "standard": 1, "deep": 2}[ctx["depth"]]
    out = []
    for row in ctx["participants"]:
        pool = POOLS.get(row["group"], DEFAULT_POOL)
        reaction = pool[row["ordinal"] % len(pool)]
        lines = LINES[reaction]
        answers = dict(zip(QUESTIONS, [f"'{headline}' {lines[0]}", *lines[1:]]))
        out.append({
            "participant": row["participant"], "answers": answers, "reaction": reaction,
            "comprehension": {"confused": "misunderstood", "mixed": "partial"}.get(reaction, "understood"),
            "themes": THEMES[reaction], "concerns": CONCERNS.get(reaction, []),
            "misunderstanding": "Reads as a travel offer, not apparel." if reaction == "confused" else None,
            "follow_ups": [{"question": q, "answer": a} for q, a in FOLLOW_UPS[:follow_ups]],
        })
    return {"interviews": out}


def analysis(ctx: Context) -> dict:
    rows = [(g["group"], g["distribution"]["rates"]["positive"]) for g in ctx["tallies"]["by_group"] if g["distribution"]["denominator"]]
    rows.sort(key=lambda r: -r[1])
    differences = [f"{rows[0][0]} has the highest positive rate ({rows[0][1]:.0%}) and {rows[-1][0]} the lowest "
                   f"({rows[-1][1]:.0%}) in these synthetic interviews."] if len(rows) > 1 else []
    misunderstandings = ctx["tallies"]["misunderstandings"]
    if misunderstandings:
        differences.append(f"The most common misunderstanding was '{misunderstandings[0]['label']}' "
                           f"({misunderstandings[0]['count']} interviews).")
    return {"group_differences": differences,
            "next_actions": ["Name the product and one concrete benefit in the headline.",
                             "Test the headline with real weekend hikers in Japan before launch."],
            "evidence_gaps": ["No observed outcomes from real people.", "Interest signals are demo fixtures, not live Qloo data."]}


def social_round(ctx: Context) -> dict:
    actions = []
    for row in ctx["participants"]:
        feed = row["feed"]
        action = ("post", "comment", "share", "ignore")[row["ordinal"] % 4]
        if action in ("comment", "share") and not feed:
            action = "post"
        current = row["current_stance"] or "neutral"
        majority = Counter(f["stance"] for f in feed if f["stance"]).most_common(1)
        stance, reason = current, "The feed did not change my view."
        if majority and majority[0][0] != current and row["ordinal"] % 3 == 0:
            stance, reason = majority[0][0], f"Several peers' posts read as {majority[0][0]}, which shifted my view."
        actions.append({"participant": row["participant"], "action": action, "stance": stance, "reason": reason,
                        "reply_to": "F1" if action in ("comment", "share") else None,
                        "text": None if action == "ignore" else POSTS[stance]})
    return {"actions": actions}


def influence(ctx: Context) -> dict:
    return {"paths": [{"summary": f"{p['group']} participants moved from {p['from']} to {p['to']} after peers' posts.",
                       "posts": [p["handle"]]} for p in ctx["posts"][:2]]}


RESPONDERS = {
    "population-groups-v1": groups,
    "population-interviews-v1": interviews,
    "population-analysis-v1": analysis,
    "social-round-v1": social_round,
    "social-influence-v1": influence,
}
