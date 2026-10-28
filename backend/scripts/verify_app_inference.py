"""Opt-in live journey through the APPLICATION (API, run engine, workflows, gateway) with real models.

Run from backend/:  NATIVEPROOF_LIVE_TESTS=1 uv run python -m scripts.verify_app_inference [--out report.md]

In-process ASGI app, dev auth, a throwaway SQLite database, and the real gateway from backend/.env. It makes a
live project and runs an ungrounded rehearsal (6 reactions, 2 segments), Voice (2 variants), Loop, Risk Radar (copy
plus a generated, non-sensitive test image for the vision model), an Arena (original vs one adaptation, 3 reactions
each), and a report with Markdown and JSON exports. Discovery is not called (Qloo verification belongs to Atlas).
Checks: run status, provider and model per step, persistence on re-read, honest provenance (no fixture data in a live
project), and the export's synthetic disclosure without a DEMO banner. The report records no keys or prompts.
"""

import argparse
import asyncio
import os
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

JP = {"country_code": "JP", "display_name": "Japan"}
CRITERIA = {"clarity": 0.3, "brand_fidelity": 0.25, "cultural_relevance": 0.3, "cultural_risk": 0.15}
TERMINAL = {"completed", "partial", "failed", "cancelled"}


def _isolate(workdir: Path) -> None:
    """Keep the real model keys from backend/.env; isolate the database, storage, and auth."""
    os.environ.update({
        "APP_ENV": "development", "AUTH_MODE": "dev", "LOG_LEVEL": "WARNING",
        "DATABASE_URL": f"sqlite+aiosqlite:///{(workdir / 'live.db').as_posix()}",
        "ASSET_STORAGE_DIR": str(workdir / "storage"),
    })


async def journey(out: Path | None = None) -> dict[str, Any]:
    import httpx

    from app.core.config import get_settings
    from app.db import models as m
    from app.db.base import Base
    from app.db.session import dispose_engine, get_engine, session
    from app.llm import gateway as gw
    from app.main import create_app
    from scripts.verify_inference import test_png

    get_settings.cache_clear()
    settings = get_settings()
    calls = {"count": 0}
    original_complete = gw.OpenAICompatibleProvider.complete

    async def counting_complete(self, request):  # counts every real chat and vision request, never the content
        calls["count"] += 1
        return await original_complete(self, request)

    gw.OpenAICompatibleProvider.complete = counting_complete
    await dispose_engine()
    async with get_engine().begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    app = create_app()
    runs: list[dict[str, Any]] = []
    checks: dict[str, bool] = {}
    async with app.router.lifespan_context(app), httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://live", headers={"Authorization": "Bearer dev-live-check"},
        timeout=60,
    ) as client:
        api = "/api/v1"

        async def post(path: str, body: dict | None = None, **kwargs: Any) -> dict:
            response = await client.post(api + path, json=body, **kwargs)
            assert response.status_code in (200, 201, 202), f"{path}: {response.status_code} {response.text[:300]}"
            return response.json()

        async def wait(accepted: dict, label: str) -> dict:
            started = time.perf_counter()
            async with asyncio.timeout(600):
                while True:
                    run = (await client.get(f"{api}/runs/{accepted['run_id']}")).json()
                    if run["status"] in TERMINAL:
                        break
                    await asyncio.sleep(1)
            async with session() as s:
                row = await s.get(m.AgentRun, __import__("uuid").UUID(run["id"]))
                steps = list(row.steps or [])
            runs.append({"label": label, "id": run["id"], "status": run["status"], "error": (run.get("error") or {}).get("code"),
                         "seconds": round(time.perf_counter() - started, 1), "steps": steps})
            return run

        project = await post("/projects", {
            "name": "Live app journey", "brand_name": "Northstar", "brand_description": "A premium outdoor lifestyle brand",
            "brand_voice": ["confident", "minimal", "adventurous"], "protected_terms": ["Northstar"],
            "prohibited_terms": ["cheap"], "target_audience": "Urban professionals who hike on weekends", "target_markets": [JP]})
        pid = project["id"]
        campaign = await post(f"/projects/{pid}/campaigns", {
            "name": "Autumn Launch Campaign", "campaign_type": "advertisement", "target_markets": [JP],
            "original_content": {"headline": "Find your next great escape", "body": "Built for the journeys that change you.",
                                 "call_to_action": "Explore the collection", "reference_terms": ["great escape"]}})
        cid, vid = campaign["id"], campaign["current_version"]["id"]
        study = await post(f"/projects/{pid}/studies", {
            "campaign_id": cid, "name": "Japan rehearsal", "market": JP,
            "research_questions": ["Is the message clear to urban weekend hikers in Japan?"],
            "simulation_config": {"response_count": 6, "segment_count": 2, "random_seed": 42}})
        rehearsal = await wait(await post(f"/studies/{study['id']}/rehearsals", {}), "rehearsal")
        adaptation = await wait(await post(f"/campaigns/{cid}/adaptations", {
            "market": JP, "variant_count": 2, "rehearsal_run_id": rehearsal["id"]}), "adaptation (Voice + Red Team)")
        adaptation_ids = (adaptation.get("result") or {}).get("ids") or []
        evaluation = await wait(await post(f"/campaigns/{cid}/evaluations", {
            "source_content_version_id": vid, "candidate_adaptation_ids": adaptation_ids[:2], "market": JP,
            "criteria": CRITERIA}), "evaluation (Loop)")
        asset = (await client.post(f"{api}/projects/{pid}/assets", data={"kind": "image"},
                                   files={"file": ("creative.png", test_png(), "image/png")})).json()
        risk = await wait(await post(f"/campaigns/{cid}/risk-scans", {
            "market": JP, "content_version_id": vid, "asset_ids": [asset["id"]]}), "risk scan (text + vision)")
        arena = await wait(await post(f"/campaigns/{cid}/arenas", {
            "study_id": study["id"], "criteria": CRITERIA, "responses_per_variant": 3,
            "variants": [{"label": "Original", "content_version_id": vid},
                         {"label": "Adaptation A", "adaptation_id": adaptation_ids[0]}]}), "arena")
        evaluation_id = ((evaluation.get("result") or {}).get("ids") or [None])[0]
        report = await post(f"/projects/{pid}/reports", {
            "campaign_id": cid, "title": "Live app journey", "rehearsal_run_id": rehearsal["id"],
            "adaptation_ids": adaptation_ids[:2], "evaluation_id": evaluation_id})
        markdown = (await client.get(f"{api}/reports/{report['id']}/export", params={"format": "markdown"})).text
        exported = await client.get(f"{api}/reports/{report['id']}/export", params={"format": "json"})

        # Persistence: every result re-reads with the same status and ids.
        rehearsal_view = (await client.get(f"{api}/studies/{study['id']}/rehearsals/{rehearsal['id']}")).json()
        scan = (await client.get(f"{api}/risk-scans/{risk['result']['ids'][0]}")).json() if risk.get("result") else {}
        arena_view = (await client.get(f"{api}/arenas/{arena['result']['ids'][0]}")).json() if arena.get("result") else {}
        evidence = (await client.get(f"{api}/projects/{pid}/evidence", params={"limit": 100})).json()["items"]
        checks["all runs completed"] = all(r["status"] == "completed" for r in runs)
        checks["every model step is nebius"] = all(
            s.get("provider") in ("nebius", "nativeproof", None) for r in runs for s in r["steps"])
        checks["rehearsal re-reads with 6 synthetic reactions"] = len(rehearsal_view.get("reactions", [])) == 6 and all(
            x["is_synthetic"] for x in rehearsal_view.get("reactions", []))
        checks["rehearsal disclosed as ungrounded"] = rehearsal_view.get("simulation_disclosure", {}).get("grounded") is False
        checks["no fixture provenance in a live project"] = all(e["retrieval_mode"] != "fixture" for e in evidence) and all(
            s.get("provider") != "fixture" for r in runs for s in r["steps"])
        checks["risk findings keep observation apart from interpretation"] = all(
            f["observation"] != f["interpretation"] for f in scan.get("findings", []))
        checks["vision analyzed the test image"] = scan.get("vision", {}).get("status") == "analyzed"
        checks["arena scored both variants"] = all(v["overall_score"] is not None for v in arena_view.get("variants", []))
        checks["export has the synthetic disclosure and no DEMO banner"] = (
            "DEMO DATA" not in markdown[:300] and "not responses from real people" in markdown)
        checks["JSON export downloads"] = exported.status_code == 200 and exported.json().get("id") == report["id"]
    gw.OpenAICompatibleProvider.complete = original_complete
    await dispose_engine()
    tokens = sum((s.get("usage") or {}).get("total_tokens") or 0 for r in runs for s in r["steps"])
    result = {"runs": runs, "checks": checks, "calls": calls["count"], "tokens": tokens, "reasoning": settings.nebius_reasoning_model}
    report_md = render(result)
    print(report_md)
    if out:
        out.write_text(report_md, encoding="utf-8")
    return result


def render(result: dict[str, Any]) -> str:
    lines = [
        "# Live app journey", "",
        f"Generated {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')} by `scripts/verify_app_inference.py`: "
        f"{result['calls']} real model requests (chat and vision), {result['tokens']} tokens. No keys or prompts recorded.", "",
        "| Run | Status | Seconds | Stage: provider / model / ms / tokens |", "|---|---|---|---|",
    ]
    for r in result["runs"]:
        stages = "<br>".join(
            f"{s['stage']}: {s.get('provider') or '-'} / {s.get('model_id') or '-'} / {s.get('latency_ms')} / "
            f"{(s.get('usage') or {}).get('total_tokens') or '-'}{' (' + s['error_code'] + ')' if s.get('error_code') else ''}"
            for s in r["steps"])
        lines.append(f"| {r['label']} | {r['status']}{' (' + r['error'] + ')' if r['error'] else ''} | {r['seconds']} | {stages} |")
    lines += ["", "| Check | Result |", "|---|---|"] + [f"| {k} | {'pass' if v else 'FAIL'} |" for k, v in result["checks"].items()]
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=None, help="Also write the markdown report to this file.")
    args = parser.parse_args()
    if os.environ.get("NATIVEPROOF_LIVE_TESTS") != "1":
        print("Skipped: set NATIVEPROOF_LIVE_TESTS=1 to make real model calls.")
        return 0
    with tempfile.TemporaryDirectory(prefix="nativeproof-live-") as workdir:
        _isolate(Path(workdir))
        from app.core.config import get_settings

        get_settings.cache_clear()
        if get_settings().nebius_api_key is None or not get_settings().nebius_default_model:
            print("Skipped: NEBIUS_API_KEY and NEBIUS_DEFAULT_MODEL are required.")
            return 0
        result = asyncio.run(journey(args.out))
    return 0 if all(result["checks"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
