"""Domain errors, the contract error envelope, and the request-context middleware.

Every error leaves the API as {"error": {code, message, details, request_id}}
(contracts/README.md section 3). Clients never see stack traces or provider details.
"""

import logging
import re
import time
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.datastructures import Headers, MutableHeaders
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.logging import request_id_var
from app.schemas.common import ErrorBody, ErrorCode, ErrorDetail, ErrorResponse

logger = logging.getLogger("nativeproof.http")

REQUEST_ID_HEADER = "X-Request-ID"
_SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
_LOCATION_PREFIXES = {"body", "query", "path", "header", "cookie"}
_CODE_BY_STATUS: dict[int, ErrorCode] = {
    401: "UNAUTHENTICATED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    405: "NOT_FOUND",
    409: "CONFLICT",
    422: "VALIDATION_ERROR",
    429: "RATE_LIMITED",
}


class AppError(Exception):
    """An expected failure with a contract error code. `message` is shown to users."""

    status_code = 500
    code: ErrorCode = "INTERNAL_ERROR"

    def __init__(self, message: str, *, details: list[ErrorDetail] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or []


class ValidationFailed(AppError):
    status_code, code = 422, "VALIDATION_ERROR"


class Unauthenticated(AppError):
    status_code, code = 401, "UNAUTHENTICATED"


class NotFound(AppError):
    status_code, code = 404, "NOT_FOUND"


class Conflict(AppError):
    status_code, code = 409, "CONFLICT"


class RateLimited(AppError):
    status_code, code = 429, "RATE_LIMITED"


class ProviderNotConfigured(AppError):
    status_code, code = 503, "PROVIDER_NOT_CONFIGURED"


class UnsupportedCapability(AppError):
    status_code, code = 501, "UNSUPPORTED_CAPABILITY"


class ProviderFailed(AppError):
    status_code, code = 502, "PROVIDER_ERROR"


class ProviderTimeout(AppError):
    status_code, code = 504, "PROVIDER_TIMEOUT"


def error_response(
    status_code: int, code: ErrorCode, message: str, details: list[ErrorDetail] | None = None
) -> JSONResponse:
    body = ErrorResponse(
        error=ErrorBody(code=code, message=message, details=details or [], request_id=request_id_var.get() or "")
    )
    headers = {"WWW-Authenticate": "Bearer"} if status_code == 401 else None
    return JSONResponse(body.model_dump(mode="json"), status_code=status_code, headers=headers)


def _field(location: tuple) -> str | None:
    parts = [str(part) for part in location]
    if parts and parts[0] in _LOCATION_PREFIXES:
        parts = parts[1:]
    return ".".join(parts) or None


def _message(error: dict) -> str:
    message = str(error.get("msg", "Invalid value."))
    return message.removeprefix("Value error, ")


async def _app_error(_: Request, exc: AppError) -> JSONResponse:
    return error_response(exc.status_code, exc.code, exc.message, exc.details)


async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
    details = [ErrorDetail(field=_field(tuple(e.get("loc", ()))), message=_message(e)) for e in exc.errors()]
    return error_response(422, "VALIDATION_ERROR", "The supplied request is invalid.", details)


async def _http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
    code = _CODE_BY_STATUS.get(exc.status_code, "INTERNAL_ERROR" if exc.status_code >= 500 else "VALIDATION_ERROR")
    message = {404: "Not found.", 405: "Method not allowed."}.get(exc.status_code, "The request failed.")
    return error_response(exc.status_code, code, message)


def install_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, _app_error)  # type: ignore[arg-type]
    app.add_exception_handler(RequestValidationError, _validation_error)  # type: ignore[arg-type]
    app.add_exception_handler(StarletteHTTPException, _http_error)  # type: ignore[arg-type]


class RequestContextMiddleware:
    """Echo or assign X-Request-ID, log one access line, and turn unhandled errors into a safe 500."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        incoming = Headers(scope=scope).get(REQUEST_ID_HEADER, "")
        request_id = incoming if _SAFE_REQUEST_ID.match(incoming) else f"req_{uuid4().hex}"
        token = request_id_var.set(request_id)
        started = time.perf_counter()
        status = {"code": 500, "sent": False}

        async def send_with_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                status["code"], status["sent"] = message["status"], True
                MutableHeaders(scope=message)[REQUEST_ID_HEADER] = request_id
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        except Exception:
            logger.exception("Unhandled error")
            if status["sent"]:
                raise
            response = error_response(500, "INTERNAL_ERROR", "An unexpected error occurred.")
            await response(scope, receive, send_with_id)
        finally:
            logger.info(
                "request",
                extra={
                    "method": scope["method"],
                    "path": scope["path"],
                    "status": status["code"],
                    "duration_ms": round((time.perf_counter() - started) * 1000, 1),
                },
            )
            request_id_var.reset(token)
