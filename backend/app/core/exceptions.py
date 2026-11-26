"""Domain exceptions and the handlers that turn them into HTTP responses.

Every error response has the same shape:
    {"error": {"code": "...", "message": "...", "details": ...}}
"""
import logging
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)

# Postgres SQLSTATEs
_FK_VIOLATION = "23503"
_UNIQUE_VIOLATION = "23505"
_CHECK_VIOLATION = "23514"
_NOT_NULL_VIOLATION = "23502"


class AppError(Exception):
    status_code = status.HTTP_400_BAD_REQUEST
    code = "bad_request"

    def __init__(self, message: str, details: Any = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details


class NotFoundError(AppError):
    status_code = status.HTTP_404_NOT_FOUND
    code = "not_found"


class ConflictError(AppError):
    status_code = status.HTTP_409_CONFLICT
    code = "conflict"


class DomainValidationError(AppError):
    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    code = "validation_error"


class ServiceUnavailableError(AppError):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    code = "service_unavailable"


def error_body(code: str, message: str, details: Any = None) -> dict[str, Any]:
    return {"error": {"code": code, "message": message, "details": jsonable_encoder(details)}}


def _integrity_error_response(exc: IntegrityError) -> tuple[int, str, str, Any]:
    orig = getattr(exc, "orig", None)
    sqlstate = getattr(orig, "sqlstate", None) or getattr(orig, "pgcode", None)
    constraint = getattr(orig, "constraint_name", None)
    details = {"constraint": constraint} if constraint else None
    if sqlstate == _UNIQUE_VIOLATION:
        return 409, "conflict", "Resource already exists", details
    if sqlstate == _FK_VIOLATION:
        return 409, "conflict", "Referenced resource is missing or still in use", details
    if sqlstate in (_CHECK_VIOLATION, _NOT_NULL_VIOLATION):
        return 422, "validation_error", "Value violates a database constraint", details
    return 409, "conflict", "Database integrity error", details


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(error_body(exc.code, exc.message, exc.details), exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            error_body("validation_error", "Request validation failed", exc.errors()), 422
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = "not_found" if exc.status_code == 404 else "http_error"
        return JSONResponse(error_body(code, str(exc.detail)), exc.status_code, headers=exc.headers)

    @app.exception_handler(IntegrityError)
    async def _integrity(_: Request, exc: IntegrityError) -> JSONResponse:
        status_code, code, message, details = _integrity_error_response(exc)
        logger.warning("integrity error: %s", exc.orig)
        return JSONResponse(error_body(code, message, details), status_code)

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled error", exc_info=exc)
        return JSONResponse(error_body("internal_error", "Internal server error"), 500)
