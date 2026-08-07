from typing import Any

import logging

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.shared.error_catalog import ERROR_CATALOG, ErrorDefinition, get_error_definition

logger = logging.getLogger("contamind.error")


class ErrorDetail(BaseModel):
    code: str
    message: str
    recoverable: bool | None = None
    details: Any = None


class ErrorResponse(BaseModel):
    success: bool = False
    error: ErrorDetail
    correlation_id: str | None = None


class AppError(Exception):
    def __init__(
        self,
        message: str,
        code: str = "APP_ERROR",
        status_code: int = status.HTTP_400_BAD_REQUEST,
        details: Any = None,
        recoverable: bool | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code
        self.details = details
        self.recoverable = recoverable


def app_error(
    code: str,
    details: Any = None,
    message: str | None = None,
    status_code: int | None = None,
) -> AppError:
    definition = get_error_definition(code)
    if code in ERROR_CATALOG:
        return AppError(
            message=message or definition.message,
            code=definition.code,
            status_code=status_code or definition.http_status,
            details=details,
            recoverable=definition.recoverable,
        )
    return AppError(
        message=message or code,
        code=code,
        status_code=status_code or status.HTTP_400_BAD_REQUEST,
        details=details,
        recoverable=None,
    )


_STATUS_CODE_TO_CATALOG: dict[int, str] = {
    401: "AUTH_INVALID_CREDENTIALS",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    409: "CONFLICT",
    503: "SERVICE_UNAVAILABLE",
}

_DEFAULT_HTTP_DETAILS = {"Not Found", "Forbidden", "Method Not Allowed"}


def _correlation_id(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


def _build_response(request: Request, error: ErrorDetail, http_status: int) -> JSONResponse:
    return JSONResponse(
        status_code=http_status,
        content=ErrorResponse(
            error=error,
            correlation_id=_correlation_id(request),
        ).model_dump(),
    )


def _handle_app_error(request: Request, exc: AppError) -> JSONResponse:
    return _build_response(
        request,
        ErrorDetail(
            code=exc.code,
            message=exc.message,
            recoverable=exc.recoverable,
            details=exc.details,
        ),
        exc.status_code,
    )


def _handle_http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    catalog_code = _STATUS_CODE_TO_CATALOG.get(exc.status_code)
    definition: ErrorDefinition | None = (
        get_error_definition(catalog_code) if catalog_code else None
    )
    details = exc.detail if isinstance(exc.detail, (dict, list)) else None
    if definition and str(exc.detail) in _DEFAULT_HTTP_DETAILS:
        message = definition.message
    else:
        message = str(exc.detail)
    return _build_response(
        request,
        ErrorDetail(
            code=definition.code if definition else "HTTP_ERROR",
            message=message,
            recoverable=definition.recoverable if definition else None,
            details=details,
        ),
        exc.status_code,
    )


def _handle_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    definition = get_error_definition("VALIDATION_ERROR")
    return _build_response(
        request,
        ErrorDetail(
            code=definition.code,
            message=definition.message,
            recoverable=definition.recoverable,
            details=exc.errors(),
        ),
        definition.http_status,
    )


def _handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
    logger.error(
        "unhandled exception",
        exc_info=exc,
        extra={"request_id": _correlation_id(request)},
    )
    definition = get_error_definition("INTERNAL_ERROR")
    return _build_response(
        request,
        ErrorDetail(
            code=definition.code,
            message=definition.message,
            recoverable=definition.recoverable,
        ),
        definition.http_status,
    )


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, _handle_app_error)
    app.add_exception_handler(RequestValidationError, _handle_validation_error)
    app.add_exception_handler(StarletteHTTPException, _handle_http_error)
    app.add_exception_handler(Exception, _handle_unexpected_error)
