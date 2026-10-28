"""HTTP routes.

Paths, methods, status codes, parameters, and response models are contract-owned;
handler bodies belong to the backend workstream.
"""

from typing import Any

from app.schemas.common import ErrorResponse

ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    401: {"model": ErrorResponse, "description": "UNAUTHENTICATED"},
    403: {"model": ErrorResponse, "description": "FORBIDDEN"},
    404: {"model": ErrorResponse, "description": "NOT_FOUND"},
    409: {"model": ErrorResponse, "description": "CONFLICT"},
    422: {"model": ErrorResponse, "description": "VALIDATION_ERROR"},
    429: {"model": ErrorResponse, "description": "RATE_LIMITED"},
    500: {"model": ErrorResponse, "description": "INTERNAL_ERROR"},
    501: {"model": ErrorResponse, "description": "UNSUPPORTED_CAPABILITY"},
    502: {"model": ErrorResponse, "description": "PROVIDER_ERROR"},
    503: {"model": ErrorResponse, "description": "PROVIDER_NOT_CONFIGURED"},
    504: {"model": ErrorResponse, "description": "PROVIDER_TIMEOUT"},
}
