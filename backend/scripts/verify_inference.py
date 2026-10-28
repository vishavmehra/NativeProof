"""Reproducible real-inference verification through the app's gateway (docs/15 §10).

Run from backend/:  uv run python -m scripts.verify_inference [--out report.md]

One real call per capability: the fast, default, and reasoning chat tiers (strict structured output), embeddings
(vector count and dimensions), and vision (a generated, non-sensitive test image). Every call goes through
LLMGateway, so routing, deadlines, retries, and validation are the production ones. The report is sanitized: no
keys, no prompts, no user data.
"""

import argparse
import asyncio
import math
import struct
import zlib
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from app.agents._common import untrusted
from app.core.config import get_settings
from app.llm.gateway import LLMError, LLMGateway
from app.llm.smoke import SmokeOut

PUBLIC_HEADLINE = "Find your next great escape"  # the public demo copy, not user data
EMBED_TEXTS = ["Weekend hiking gear for autumn trails.", "Minimal design for city commuters."]
Row = tuple[str, str | None, str | None, str, int | None, str]


def test_png() -> bytes:
    """A 96x64 PNG: white background, a blue horizontal bar, and a red square. Built with the stdlib."""
    width, height = 96, 64

    def pixel(x: int, y: int) -> tuple[int, int, int]:
        if 8 <= y < 20:
            return 30, 80, 220
        if 32 <= y < 56 and 36 <= x < 60:
            return 220, 40, 40
        return 255, 255, 255

    raw = b"".join(b"\x00" + b"".join(bytes(pixel(x, y)) for x in range(width)) for y in range(height))

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


def failed(capability: str, exc: LLMError) -> Row:
    return capability, exc.trace.provider, exc.trace.model_id, f"fail ({exc.code})", exc.trace.latency_ms, exc.message


async def chat(gateway: LLMGateway, capability: str, task: str) -> Row:
    try:
        result = await gateway.generate_structured(
            task=task, stage="verification", agent="verify", schema=SmokeOut, prompt_version="verify-v1",
            temperature=0.0, system="Classify how a reader in Japan might react to an outdoor-apparel headline.",
            user=untrusted("headline", PUBLIC_HEADLINE),
        )
    except LLMError as exc:
        return failed(capability, exc)
    t = result.trace
    tokens = f"; tokens in/out {t.usage.input_tokens}/{t.usage.output_tokens}" if t.usage else "; usage not reported"
    retries = f"; retries {t.retries}" if t.retries else ""
    return capability, t.provider, t.model_id, "ok", t.latency_ms, f"strict schema valid (sentiment={result.value.sentiment}){tokens}{retries}"


async def embeddings(gateway: LLMGateway, settings) -> Row:
    client = gateway.capability("embeddings")
    if client is None:
        return "embeddings", settings.embedding_provider, settings.embedding_model, "not configured", None, "EMBEDDING_* unset or unverified"
    try:
        result = await client.embed(EMBED_TEXTS, kind="document", stage="verification", agent="verify")
    except LLMError as exc:
        return failed("embeddings", exc)
    dims = sorted({len(v) for v in result.vectors})
    norms = ", ".join(f"{math.sqrt(sum(x * x for x in v)):.3f}" for v in result.vectors)
    ok = len(result.vectors) == len(EMBED_TEXTS) and dims == [settings.embedding_dimensions]
    summary = f"{len(result.vectors)} vectors, dimensions {dims} (expected {settings.embedding_dimensions}), L2 norms {norms}"
    t = result.trace
    return "embeddings", t.provider, t.model_id, "ok" if ok else "fail (shape)", t.latency_ms, summary


async def vision(gateway: LLMGateway, settings) -> Row:
    client = gateway.capability("vision")
    if client is None:
        return "vision", settings.vision_provider, settings.vision_model, "not configured", None, "VISION_* unset or unverified"
    try:
        result = await client.observe(uuid4(), test_png(), "image/png", stage="verification", agent="verify")
    except LLMError as exc:
        return failed("vision", exc)
    status, observations = result.status, result.observations
    ok = status.status == "analyzed" and bool(observations)
    summary = f"{len(observations)} observation(s) of the test image: " + "; ".join(
        f"{o.kind}: {o.description[:70]}" for o in observations[:4])
    latency = result.trace.latency_ms if result.trace else None
    return "vision", status.provider, status.model_id, "ok" if ok else f"fail ({status.status})", latency, summary if ok else (status.message or summary)


async def main(out: Path | None) -> int:
    settings = get_settings()
    gateway = LLMGateway(settings)
    if not gateway.is_configured():
        print("NOT CONFIGURED: set NEBIUS_API_KEY and NEBIUS_DEFAULT_MODEL in backend/.env")
        return 2
    rows = [
        await chat(gateway, "chat: fast", "extraction"),
        await chat(gateway, "chat: default", "research_synthesis"),
        await chat(gateway, "chat: reasoning", "risk_analysis"),
        await embeddings(gateway, settings),
        await vision(gateway, settings),
    ]
    stamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    calls = sum(1 for r in rows if r[4] is not None)
    lines = [
        "# Real-inference verification", "",
        f"Generated {stamp} by `scripts/verify_inference.py`: {calls} real provider calls through `LLMGateway`. "
        "Keys, prompts, and user data are not recorded.", "",
        "| Capability | Provider | Model | Result | Latency (ms) | Output summary |", "|---|---|---|---|---|---|",
    ]
    lines += [f"| {c} | {p or '-'} | `{m or 'unset'}` | {r} | {lat if lat is not None else '-'} | {s.replace('|', '/')} |"
              for c, p, m, r, lat, s in rows]
    report = "\n".join(lines) + "\n"
    print(report)
    if out:
        out.write_text(report, encoding="utf-8")
    return 0 if all(r[3].startswith(("ok", "not configured", "configured")) for r in rows) else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=None, help="Also write the markdown report to this file.")
    raise SystemExit(asyncio.run(main(parser.parse_args().out)))
