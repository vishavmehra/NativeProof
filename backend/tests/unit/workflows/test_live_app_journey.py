"""Opt-in live regression: the full journey through the application with real models.

Skipped unless NATIVEPROOF_LIVE_TESTS=1 and a Nebius key is configured (about 15 model requests per run).
"""

import os
import tempfile
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("NATIVEPROOF_LIVE_TESTS") != "1", reason="live model calls are opt-in (NATIVEPROOF_LIVE_TESTS=1)"
)


async def test_live_app_journey(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import get_settings
    from scripts import verify_app_inference as live

    with tempfile.TemporaryDirectory(prefix="nativeproof-live-") as workdir:
        live._isolate(Path(workdir))
        get_settings.cache_clear()
        if get_settings().nebius_api_key is None:
            pytest.skip("NEBIUS_API_KEY is not configured")
        result = await live.journey()
        get_settings.cache_clear()
    failed = [name for name, ok in result["checks"].items() if not ok]
    assert not failed, failed
    assert result["calls"] <= 30  # call bound for this journey (measured: 15)
