from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.routing import APIRoute

from app.api.routes import (
    ERROR_RESPONSES,
    adaptations,
    arenas,
    assets,
    brand,
    campaigns,
    discoveries,
    evaluations,
    evidence,
    graph,
    health,
    markets,
    populations,
    profiles,
    projects,
    reports,
    risk,
    runs,
    search,
    studies,
    trends,
)
from app.core.config import Settings, get_settings
from app.core.errors import REQUEST_ID_HEADER, RequestContextMiddleware, install_error_handlers
from app.core.logging import configure_logging
from app.db.session import dispose_engine
from app.services import runs as run_engine

ROUTERS = (
    projects,
    brand,
    campaigns,
    discoveries,
    profiles,
    markets,
    trends,
    studies,
    populations,
    arenas,
    risk,
    adaptations,
    evaluations,
    evidence,
    graph,
    search,
    assets,
    reports,
    runs,
)

API_PREFIX = "/api/v1"


def _operation_id(route: APIRoute) -> str:
    return route.name


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    await run_engine.mark_interrupted_runs()
    yield
    await run_engine.shutdown()
    await dispose_engine()


def check_production(settings: Settings) -> None:
    """Fail closed: refuse to start a production app without real auth, a real database, and explicit origins.
    (AUTH_MODE=dev under APP_ENV=production is already refused when the settings load.)"""
    problems = []
    if settings.auth_mode != "supabase" or not settings.supabase_url:
        problems.append("AUTH_MODE=supabase with SUPABASE_URL set")
    if not settings.database_url.startswith("postgresql"):
        problems.append("DATABASE_URL pointing at Postgres (SQLite is for development and tests)")
    if not settings.cors_origins or "*" in settings.cors_origins:
        problems.append("FRONTEND_ORIGINS listing explicit origins")
    if problems:
        raise RuntimeError("APP_ENV=production requires: " + "; ".join(problems) + ".")


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings)
    production = settings.app_env == "production"
    if production:
        check_production(settings)
    # Interactive docs are a development aid; production serves only the API, /health, and /ready.
    docs = {"docs_url": None, "redoc_url": None, "openapi_url": None} if production else {}
    app = FastAPI(
        title="Nativeproof API", version="0.1.0", generate_unique_id_function=_operation_id, lifespan=lifespan, **docs
    )
    install_error_handlers(app)
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", REQUEST_ID_HEADER],
        expose_headers=[REQUEST_ID_HEADER, "Content-Disposition"],
    )
    app.include_router(health.router)
    api = APIRouter(prefix=API_PREFIX, responses=ERROR_RESPONSES)
    for module in ROUTERS:
        api.include_router(module.router)
    app.include_router(api)
    return app


app = create_app()
