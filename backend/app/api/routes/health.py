from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.schemas.health import Health, Readiness
from app.services.providers import readiness

router = APIRouter(tags=["health"])


@router.api_route("/health", methods=["GET", "HEAD"], response_model=Health)  # uptime monitors probe with HEAD
async def health() -> Health:
    return Health(status="ok")


@router.get("/ready", response_model=Readiness)
async def ready() -> Readiness | JSONResponse:
    """Configuration-level readiness. Must not make paid or slow provider calls."""
    result = await readiness()
    if result.status == "not_ready":  # same body; 503 so load balancers stop routing here
        return JSONResponse(result.model_dump(mode="json"), status_code=503)
    return result
