"""Health, readiness, request ids, the error envelope, and CORS."""

import httpx
import pytest

from tests.conftest import BOB


async def test_health(client: httpx.AsyncClient) -> None:
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_ready_reports_configuration_without_provider_calls(client: httpx.AsyncClient) -> None:
    response = await client.get("/ready")
    assert response.status_code == 200
    assert response.json() == {
        "status": "degraded",
        "dependencies": {"database": "available", "llm_provider": "not_configured", "qloo": "not_configured"},
        "capabilities": {"embeddings": "not_configured", "vision": "not_configured", "reranking": "not_configured"},
        "live_mode_available": False,
        "demo_mode_available": True,
    }


async def test_ready_live_when_both_providers_configured(client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import get_settings

    import sys

    values = {"QLOO_API_KEY": "k", "QLOO_BIN": sys.executable, "NEBIUS_API_KEY": "k", "NEBIUS_DEFAULT_MODEL": "m"}
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    get_settings.cache_clear()
    body = (await client.get("/ready")).json()
    assert body["status"] == "ready" and body["live_mode_available"] is True


async def test_unverified_capability_model_is_not_reported_configured(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.core.config import get_settings

    for name, value in {"VISION_MODEL": "unverified/model", "NEBIUS_API_KEY": "k", "OPENROUTER_API_KEY": "k"}.items():
        monkeypatch.setenv(name, value)
    get_settings.cache_clear()
    capabilities = (await client.get("/ready")).json()["capabilities"]
    assert capabilities["vision"] == "not_configured"
    assert capabilities["reranking"] == "not_configured"


async def test_request_id_is_echoed_or_generated(client: httpx.AsyncClient) -> None:
    echoed = await client.get("/health", headers={"X-Request-ID": "req-abc.123"})
    assert echoed.headers["X-Request-ID"] == "req-abc.123"
    generated = await client.get("/health", headers={"X-Request-ID": "bad id\twith spaces"})
    assert generated.headers["X-Request-ID"].startswith("req_")


async def test_unknown_route_uses_envelope(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/v1/nope")
    assert response.status_code == 404
    error = response.json()["error"]
    assert error["code"] == "NOT_FOUND" and error["request_id"] == response.headers["X-Request-ID"]


async def test_validation_errors_map_to_envelope_with_fields(client: httpx.AsyncClient) -> None:
    project = (await client.post("/api/v1/projects", json={"name": "P", "brand_name": "B"})).json()
    response = await client.post(
        f"/api/v1/projects/{project['id']}/campaigns",
        json={
            "name": "C", "campaign_type": "advertisement", "original_content": {"headline": "Hi"},
            "evaluation_criteria": {"clarity": 0.3, "brand_fidelity": 0.25, "cultural_relevance": 0.25, "cultural_risk": 0.15},
        },
    )
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "VALIDATION_ERROR"
    assert error["message"] == "The supplied request is invalid."
    assert {"field": "evaluation_criteria", "message": "Weights must sum to 1.0; got 0.950."} in error["details"]


async def test_unknown_fields_and_bad_params_are_rejected(client: httpx.AsyncClient) -> None:
    response = await client.post("/api/v1/projects", json={"name": "P", "brand_name": "B", "owner_id": "x"})
    assert response.status_code == 422
    assert response.json()["error"]["details"][0]["field"] == "owner_id"
    response = await client.get("/api/v1/projects", params={"limit": 0})
    assert response.status_code == 422
    assert response.json()["error"]["details"][0]["field"] == "limit"


async def test_unhandled_errors_become_safe_500(client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import projects

    async def boom(*_: object) -> None:
        raise RuntimeError("secret internal detail")

    monkeypatch.setattr(projects, "list_projects", boom)
    response = await client.get("/api/v1/projects")
    assert response.status_code == 500
    body = response.json()
    assert body["error"]["code"] == "INTERNAL_ERROR"
    assert "secret" not in response.text and "Traceback" not in response.text
    assert response.headers["X-Request-ID"] == body["error"]["request_id"]


async def test_cors_preflight_allows_frontend_and_exposes_headers(client: httpx.AsyncClient) -> None:
    preflight = await client.options(
        "/api/v1/projects",
        headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": "POST",
                 "Access-Control-Request-Headers": "authorization,content-type,x-request-id"},
    )
    assert preflight.status_code == 200
    assert preflight.headers["access-control-allow-origin"] == "http://localhost:3000"
    simple = await client.get("/health", headers={"Origin": "http://localhost:3000"})
    exposed = simple.headers["access-control-expose-headers"].lower()
    assert "x-request-id" in exposed and "content-disposition" in exposed
    blocked = await client.get("/health", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in blocked.headers


async def test_cors_preflight_allows_put_for_brand_memory(client: httpx.AsyncClient) -> None:
    """Brand Memory saves with PUT /projects/{id}/brand; a browser preflight without PUT blocks every save."""
    preflight = await client.options(
        "/api/v1/projects/00000000-0000-0000-0000-000000000000/brand",
        headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": "PUT",
                 "Access-Control-Request-Headers": "authorization,content-type"},
    )
    assert preflight.status_code == 200
    assert "PUT" in preflight.headers["access-control-allow-methods"]


async def test_other_users_are_isolated(client: httpx.AsyncClient) -> None:
    project = (await client.post("/api/v1/projects", json={"name": "P", "brand_name": "B"})).json()
    assert (await client.get(f"/api/v1/projects/{project['id']}", headers=BOB)).status_code == 404
    assert (await client.get("/api/v1/projects", headers=BOB)).json()["total"] == 0


def test_log_formatter_redacts_secrets_and_bearer_tokens() -> None:
    import logging

    from app.core.logging import JsonFormatter

    formatter = JsonFormatter(["sk-very-secret"])
    record = logging.LogRecord("t", logging.INFO, __file__, 1, "key sk-very-secret header Bearer abc.def", None, None)
    output = formatter.format(record)
    assert "sk-very-secret" not in output and "abc.def" not in output and "[REDACTED]" in output
