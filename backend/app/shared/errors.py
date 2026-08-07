from typing import Any

import logging

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger("contamind.error")


class ErrorDetail(BaseModel):
    code: str
    message: str
    details: Any = None


class ErrorResponse(BaseModel):
    success: bool = False
    error: ErrorDetail
    correlation_id: str | None = None


class AppError(Exception):
    def __init__(
        self,
        message: str,
        code: str = "app_error",
        status_code: int = status.HTTP_400_BAD_REQUEST,
        details: Any = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code
        self.details = details


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
        ErrorDetail(code=exc.code, message=exc.message, details=exc.details),
        exc.status_code,
    )


def _handle_http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    details = exc.detail if isinstance(exc.detail, (dict, list)) else None
    return _build_response(
        request,
        ErrorDetail(
            code="http_error",
            message=str(exc.detail),
            details=details,
        ),
        exc.status_code,
    )


def _handle_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    return _build_response(
        request,
        ErrorDetail(
            code="validation_error",
            message="Datos de entrada inválidos.",
            details=exc.errors(),
        ),
        status.HTTP_422_UNPROCESSABLE_ENTITY,
    )


def _handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
    logger.error(
        "unhandled exception",
        exc_info=exc,
        extra={"request_id": _correlation_id(request)},
    )
    return _build_response(
        request,
        ErrorDetail(
            code="internal_error",
            message="Ocurrió un error interno del servidor.",
        ),
        status.HTTP_500_INTERNAL_SERVER_ERROR,
    )


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, _handle_app_error)
    app.add_exception_handler(RequestValidationError, _handle_validation_error)
    app.add_exception_handler(StarletteHTTPException, _handle_http_error)
    app.add_exception_handler(Exception, _handle_unexpected_error)
