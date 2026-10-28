"""Live Qloo smoke check: one real call per endpoint Nativeproof uses. Run it right after adding QLOO_API_KEY.

    cd backend
    uv run python -m scripts.qloo_live_smoke [--transport auto|harness|rest] [--base-url https://...] [--out FILE]

Calls, in order (stops early only when nothing can follow):
  1. resolve_concept(TERM)        GET /v2/tags (+ GET /search when no tag matches near-exactly)
  2. resolve_concept(ENTITY_TERM) GET /v2/tags + GET /search
  3. related_interests(seed)      GET /v2/insights (filter.type=urn:entity:brand)
  4. related_interests(seed, JP)  GET /v2/insights with signal.location.query
  5. audience_demographics(item)  GET /v2/insights (filter.type=urn:demographics)
  6. trends(item, 90 days)        GET /v2/trending
Prints and writes a sanitized Markdown report: step, endpoint, status, latency, result count, a few names and
ids, and the safe error code. The key is never printed. Exit code 0 when no step errored, 1 otherwise,
2 without QLOO_API_KEY, 3 when no transport is available.
"""

import argparse
import asyncio
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from app.core.config import get_settings
from app.integrations.qloo import QlooEntity, get_qloo_service
from app.schemas.common import Market


def _names(entities: list[QlooEntity]) -> str:
    return "; ".join(f"{e.name} ({e.entity_id})" for e in entities[:3]) or "-"


async def run(args: argparse.Namespace) -> int:
    settings = get_settings()
    key = settings.qloo_api_key
    if key is None or not key.get_secret_value().strip():
        print("QLOO_API_KEY is not configured: add it to backend/.env, then rerun this script.")
        return 2
    overrides = {name: value for name, value in (("qloo_transport", args.transport), ("qloo_base_url", args.base_url)) if value}
    effective: Any = settings
    if overrides:  # QLOO_TRANSPORT / QLOO_BASE_URL settings may not exist yet; pass them as plain attributes
        effective = SimpleNamespace(**{name: getattr(settings, name) for name in type(settings).model_fields}, **overrides)
    service = get_qloo_service("live", effective)
    if not service.is_configured():
        print("No Qloo transport is available: install the harness (npm ci in backend/qloo) or use --transport rest.")
        return 3

    rows: list[tuple[str, str, str, int, str, str, str]] = []

    async def step(label: str, endpoint: str, call: Any) -> Any:
        started = time.perf_counter()
        result = await call
        latency = int((time.perf_counter() - started) * 1000)
        error = getattr(result, "error", None)
        found = (getattr(result, "candidates", None) or ([result.match] if getattr(result, "match", None) else [])
                 or getattr(result, "items", None) or [])
        count = len(found) or len(getattr(result, "segments", None) or getattr(result, "points", None) or [])
        sample = _names(found) if found else "-"
        rows.append((label, endpoint, result.status, latency, str(count), sample,
                     f"{error.code}: {error.message}" if error else "-"))
        return result

    concept = await step("resolve concept", "GET /v2/tags (+ /search)", service.resolve_concept(args.term))
    if concept.error and concept.error.code == "QLOO_AUTH":
        rows.append(("stopped", "-", "-", 0, "0", "-", "The key was rejected; no further calls were made."))
        seed = entity_concept = None
    else:
        entity_concept = await step("resolve entity", "GET /v2/tags + GET /search", service.resolve_concept(args.entity_term))
        seed = concept.match or (concept.candidates[0] if concept.candidates else None)
    if seed is not None and entity_concept is not None:
        related = await step("related interests", "GET /v2/insights", service.related_interests(seed, market=None, limit=5))
        await step("related interests (market)", "GET /v2/insights + signal.location.query", service.related_interests(
            seed, market=Market(country_code="JP", display_name=args.market), limit=5))
        item = (related.items[0] if related.items else None) or entity_concept.match
        if item is not None:
            await step("audience demographics", "GET /v2/insights urn:demographics", service.audience_demographics(item))
            end = datetime.now(UTC).date()
            entity_type = (item.entity_type or "urn:entity:brand").rsplit(":", 1)[-1]
            await step("trends (90 days)", "GET /v2/trending", service.trends(
                item, entity_type=entity_type if entity_type in INSIGHTS_TYPES else "brand",  # type: ignore[arg-type]
                start_date=(end - timedelta(days=90)).isoformat(), end_date=end.isoformat()))

    transport = getattr(service, "transport", "unknown")
    lines = [
        f"# Qloo live smoke ({datetime.now(UTC):%Y-%m-%d %H:%M} UTC)", "",
        f"Transport: {transport}; base URL: {getattr(effective, 'qloo_base_url', None) or 'https://api.qloo.com'}", "",
        "| step | endpoint | status | latency ms | results | sample (name, id) | error |",
        "|---|---|---|---|---|---|---|",
        *(f"| {' | '.join(str(cell) for cell in row)} |" for row in rows),
    ]
    report = "\n".join(lines) + "\n"
    print(report)
    if args.out:
        Path(args.out).write_text(report, encoding="utf-8")
    return 1 if any(row[2] == "error" for row in rows) else 0


INSIGHTS_TYPES = {"artist", "book", "brand", "movie", "person", "place", "podcast", "tv_show", "videogame"}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--transport", choices=["auto", "harness", "rest"])
    parser.add_argument("--base-url")
    parser.add_argument("--term", default="hiking")
    parser.add_argument("--entity-term", default="Patagonia")
    parser.add_argument("--market", default="Japan")
    parser.add_argument("--out", default="qloo_live_smoke_report.md")
    sys.exit(asyncio.run(run(parser.parse_args())))


if __name__ == "__main__":
    main()
