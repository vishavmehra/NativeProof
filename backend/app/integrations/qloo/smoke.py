"""Live Qloo smoke check: one find_tags call through the real harness. Not part of pytest.

Usage (from backend/):  uv run python -m app.integrations.qloo.smoke "outdoor exploration"
Exit codes: 0 ok, 1 Qloo returned an error, 2 QLOO_API_KEY missing, 3 harness missing.
Prints a sanitized summary only; the credential is never printed.
"""

import asyncio
import sys

from app.core.config import get_settings
from app.integrations.qloo.service import get_qloo_service


async def main(query: str) -> int:
    settings = get_settings()
    if settings.qloo_api_key is None or not settings.qloo_api_key.get_secret_value().strip():
        print("QLOO_API_KEY not configured: live Qloo verification is blocked. Set it in backend/.env or the environment.")
        return 2
    service = get_qloo_service("live", settings)
    if not service.is_configured():
        print("Qloo harness not found: run `npm ci` in backend/qloo (Node >= 22.19) or set QLOO_BIN.")
        return 3

    result = await service.resolve_concept(query)
    print(f"query: {result.query!r}\nstatus: {result.status}")
    if result.match:
        print(f"match: {result.match.name} | {result.match.entity_id} | {result.match.entity_type}")
    for candidate in result.candidates:
        print(f"candidate: {candidate.name} | {candidate.entity_id} | {candidate.entity_type}")
    for draft in result.evidence:
        provenance = draft.provenance
        hashes = f"request {provenance.request_hash[:12]} response {provenance.response_hash[:12]}" if provenance else "-"
        print(f"evidence: {draft.title} | {draft.retrieval_mode} | {hashes}")
    for limitation in result.limitations:
        print(f"limitation: {limitation}")
    if result.error:
        print(f"error: {result.error.code} (retryable={result.error.retryable}): {result.error.message}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main(" ".join(sys.argv[1:]) or "outdoor exploration")))
