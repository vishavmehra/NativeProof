"""Unexpected errors become a safe 500 envelope: no stack trace, exception text, paths, or secrets (NFR-001)."""

import pytest

from tests.integration._support import API, expect_error, running_app

DUMMY = "sk-qa-DUMMY-hygiene-5d7f9b1c3e"
LEAKY_MESSAGE = f"qa boom: token={DUMMY} at C:\\srv\\nativeproof\\app\\secret_module.py line 42"


def add_boom_routes(app):  # type: ignore[no-untyped-def]
    async def boom() -> None:
        raise RuntimeError(LEAKY_MESSAGE)

    async def boom_lookup() -> None:
        {}["qa-missing-key"]  # KeyError deep in handler code

    app.add_api_route(f"{API}/__qa_boom", boom, methods=["GET"])
    app.add_api_route(f"{API}/__qa_boom_lookup", boom_lookup, methods=["GET"])


async def test_unhandled_errors_are_safe_500s(qa_env: dict[str, str], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NEBIUS_API_KEY", DUMMY)
    async with running_app(raise_app_exceptions=False, customize=add_boom_routes) as app:
        for path in (f"{API}/__qa_boom", f"{API}/__qa_boom_lookup"):
            response = await app.client.get(path, headers={"X-Request-ID": "qa-boom-1"})
            envelope = expect_error(response, 500, "INTERNAL_ERROR")
            assert envelope.error.request_id == "qa-boom-1", "500s keep the request id for support"
            assert envelope.error.details == []
            text = response.text
            for marker in ("Traceback", "RuntimeError", "KeyError", 'File "', "secret_module", "qa boom", "qa-missing-key", DUMMY):
                assert marker not in text, f"500 body exposes internal detail ({marker[:12]}...)"
            assert response.headers["content-type"].startswith("application/json")
