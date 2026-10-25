"""Domain exceptions and their HTTP representation."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.core.logging import get_logger

logger = get_logger(__name__)


class AppError(Exception):
    """Base class for errors that map onto a clean HTTP response."""

    status_code = 400
    code = "app_error"

    def __init__(self, message: str, *, details: dict | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


class NotFoundError(AppError):
    status_code = 404
    code = "not_found"


class ConflictError(AppError):
    status_code = 409
    code = "conflict"


class ValidationError(AppError):
    status_code = 422
    code = "validation_error"


class AuthError(AppError):
    """Not authenticated: no token, or one that cannot be trusted."""

    status_code = 401
    code = "unauthorized"


class ForbiddenError(AppError):
    """Authenticated, but not allowed to do this.

    Distinct from AuthError on purpose: a 401 tells the client to re-login,
    which for a permission problem sends the operator round a loop that can
    never succeed.
    """

    status_code = 403
    code = "forbidden"


class NotConfiguredError(AppError):
    """A feature that needs setup the deployment does not have (e.g. SMTP)."""

    status_code = 503
    code = "not_configured"


class StreamError(AppError):
    status_code = 503
    code = "stream_error"


class ModelNotAvailableError(AppError):
    status_code = 503
    code = "model_unavailable"


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _handle_app_error(_: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": exc.code,
                "message": exc.message,
                "details": exc.details,
            },
            # Without this header a 401 is just a number; with it the client
            # knows the scheme it failed to satisfy.
            headers={"WWW-Authenticate": "Bearer"}
            if isinstance(exc, AuthError)
            else None,
        )

    @app.exception_handler(Exception)
    async def _handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled error on %s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=500,
            content={
                "error": "internal_error",
                "message": "An unexpected error occurred.",
                "details": {},
            },
        )
