"""Production fails closed: no dev auth, no missing essentials, no debug or docs routes."""

import json
from pathlib import Path

import pytest
from fastapi.routing import APIRoute
from pydantic import ValidationError

from app.core.config import Settings, get_settings

HTTP_METHODS = {"get", "head", "post", "put", "patch", "delete"}
PROD = {
    "APP_ENV": "production",
    "AUTH_MODE": "supabase",
    "SUPABASE_URL": "https://example.supabase.co",
    "DATABASE_URL": "postgresql+asyncpg://user:pw@db.example.supabase.co:5432/postgres?ssl=require",
    "FRONTEND_ORIGINS": "https://app.example.com",
}


@pytest.fixture
def production(monkeypatch: pytest.MonkeyPatch, test_settings: None) -> pytest.MonkeyPatch:
    for name, value in PROD.items():
        monkeypatch.setenv(name, value)
    get_settings.cache_clear()
    return monkeypatch


def test_dev_auth_is_refused_in_production() -> None:
    with pytest.raises(ValidationError, match="AUTH_MODE=dev is refused"):
        Settings(_env_file=None, app_env="production", auth_mode="dev")  # type: ignore[call-arg]


@pytest.mark.parametrize(
    ("override", "missing"),
    [
        ({"SUPABASE_URL": ""}, "SUPABASE_URL"),
        ({"DATABASE_URL": "sqlite+aiosqlite:///./prod.db"}, "DATABASE_URL pointing at Postgres"),
        ({"FRONTEND_ORIGINS": "*"}, "FRONTEND_ORIGINS"),
    ],
)
def test_production_refuses_to_start_without_essentials(production: pytest.MonkeyPatch, override: dict, missing: str) -> None:
    from app.main import create_app

    for name, value in override.items():
        production.setenv(name, value)
    get_settings.cache_clear()
    with pytest.raises(RuntimeError, match=missing):
        create_app()


def test_production_serves_only_contract_routes(production: pytest.MonkeyPatch) -> None:
    from app.api.routes import health
    from app.main import ROUTERS, create_app

    app = create_app()
    assert [r.path for r in app.routes if hasattr(r, "path")] == []  # no docs, redoc, or openapi.json routes
    routes = [route for module in (*ROUTERS, health) for route in module.router.routes]
    assert all(isinstance(route, APIRoute) and route.include_in_schema for route in routes)  # nothing hidden
    for route in routes:
        assert not any(word in route.path for word in ("debug", "admin", "internal", "test")), route.path
    schema_paths = set(app.openapi()["paths"])
    assert all(p in {"/health", "/ready"} or p.startswith("/api/v1/") for p in schema_paths)
    contract = json.loads((Path(__file__).resolve().parents[3] / "contracts" / "openapi.json").read_text(encoding="utf-8"))
    operations = sum(1 for item in contract["paths"].values() for method in item if method in HTTP_METHODS)
    assert sum(len(route.methods) for route in routes) == operations  # exactly the committed contract's operations
