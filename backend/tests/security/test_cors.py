"""CORS allows only the configured FRONTEND_ORIGINS (contracts/README.md §10)."""

import pytest

from tests.integration._support import API, running_app

ALLOWED = ("http://localhost:3000", "https://app.nativeproof.test")
DISALLOWED = ("https://evil.example", "http://localhost:3001", "null", "https://app.nativeproof.test.evil.example")


def preflight(origin: str) -> dict[str, str]:
    return {
        "Origin": origin,
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "authorization,content-type,x-request-id",
    }


async def test_cors_allows_only_configured_origins(qa_env: dict[str, str], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FRONTEND_ORIGINS", ",".join(ALLOWED))
    async with running_app() as app:
        for origin in ALLOWED:
            response = await app.client.options(f"{API}/projects", headers=preflight(origin))
            assert response.status_code == 200, f"preflight from {origin}: {response.status_code}"
            assert response.headers.get("access-control-allow-origin") == origin
            allowed_headers = response.headers.get("access-control-allow-headers", "").lower()
            assert "authorization" in allowed_headers or allowed_headers == "*", (
                "the browser frontend sends Authorization: Bearer (README §4)"
            )
            simple = await app.client.get("/health", headers={"Origin": origin})
            assert simple.headers.get("access-control-allow-origin") == origin
        for origin in DISALLOWED:
            response = await app.client.options(f"{API}/projects", headers=preflight(origin))
            assert response.headers.get("access-control-allow-origin") in (None, ""), f"preflight allowed {origin}"
            simple = await app.client.get("/health", headers={"Origin": origin})
            assert simple.headers.get("access-control-allow-origin") in (None, ""), f"response allowed {origin}"


async def test_cors_never_wildcards(qa_env: dict[str, str]) -> None:
    async with running_app() as app:
        response = await app.client.options(f"{API}/projects", headers=preflight("http://localhost:3000"))
        assert response.headers.get("access-control-allow-origin") == "http://localhost:3000"
        anything = await app.client.get("/health", headers={"Origin": "https://random.example"})
        assert anything.headers.get("access-control-allow-origin") != "*"
