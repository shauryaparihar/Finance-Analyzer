"""
One safe error shape for every failure:
    {"error": {"code": "...", "message": "...", "request_id": "...", "details": {}}}
Stack traces, SQL text and raw exception strings stay in the server log, never in the response.
"""
import logging
import re
import time
import uuid
from typing import Any, Optional

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from backend.core.logging import log_event, request_id_var

logger = logging.getLogger("finsight.api")

REQUEST_ID_HEADER = "X-Request-ID"
_SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{8,64}$")

_STATUS_CODES = {
    400: "BAD_REQUEST",
    401: "NOT_AUTHENTICATED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    405: "METHOD_NOT_ALLOWED",
    413: "PAYLOAD_TOO_LARGE",
    429: "TOO_MANY_REQUESTS",
}


class AppError(Exception):
    """An expected failure with a stable machine-readable code and a message safe to show users."""

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        details: Optional[dict[str, Any]] = None,
        headers: Optional[dict[str, str]] = None,
    ):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details or {}
        self.headers = headers or {}


def get_request_id(request: Request) -> str:
    return getattr(request.state, "request_id", "unknown")


def error_response(
    request: Request,
    status_code: int,
    code: str,
    message: str,
    details: Optional[dict[str, Any]] = None,
    headers: Optional[dict[str, str]] = None,
) -> JSONResponse:
    request_id = get_request_id(request)
    body = {"error": {"code": code, "message": message, "request_id": request_id, "details": details or {}}}
    response_headers = {REQUEST_ID_HEADER: request_id, **(headers or {})}
    return JSONResponse(status_code=status_code, content=body, headers=response_headers)


def register_error_handling(app: FastAPI) -> None:
    @app.middleware("http")
    async def request_id_middleware(request: Request, call_next):
        incoming = request.headers.get(REQUEST_ID_HEADER, "")
        request.state.request_id = incoming if _SAFE_REQUEST_ID.match(incoming) else uuid.uuid4().hex
        request_id_var.set(request.state.request_id)
        started = time.perf_counter()
        response = await call_next(request)
        response.headers[REQUEST_ID_HEADER] = request.state.request_id
        log_event(
            logger,
            logging.INFO,
            "request",
            method=request.method,
            path=request.url.path,  # the path only: no query string and no body
            status=response.status_code,
            duration_ms=int((time.perf_counter() - started) * 1000),
            user_id=getattr(request.state, "user_id", None),
        )
        return response

    @app.exception_handler(AppError)
    async def handle_app_error(request: Request, exc: AppError):
        return error_response(request, exc.status_code, exc.code, exc.message, exc.details, exc.headers)

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_exception(request: Request, exc: StarletteHTTPException):
        code = _STATUS_CODES.get(exc.status_code, "HTTP_ERROR")
        message = exc.detail if isinstance(exc.detail, str) else "Request failed"
        return error_response(request, exc.status_code, code, message)

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(request: Request, exc: RequestValidationError):
        # Only locations and messages: never echo submitted values (they may contain passwords).
        problems = [{"field": ".".join(str(p) for p in e["loc"] if p != "body"), "message": e["msg"]} for e in exc.errors()]
        return error_response(request, 422, "VALIDATION_ERROR", "The request is not valid.", {"problems": problems})

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception):
        log_event(logger, logging.ERROR, "unhandled_error", path=request.url.path, exc_info=exc)
        return error_response(request, 500, "INTERNAL_ERROR", "Something went wrong. Please try again later.")
