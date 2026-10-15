"""Typed application errors and the uniform error envelope.

Error body: {code, message, retryable, details, run_id}
Cross-owner access always answers 404 so resource existence is not leaked.
"""

from __future__ import annotations

from typing import Any


class AppError(Exception):
    status_code = 400
    code = "BAD_REQUEST"
    retryable = False

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        details: dict[str, Any] | None = None,
        status_code: int | None = None,
        retryable: bool | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        if code:
            self.code = code
        if status_code:
            self.status_code = status_code
        if retryable is not None:
            self.retryable = retryable
        self.details = details or {}

    def to_body(self, run_id: str | None = None) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "retryable": self.retryable,
            "details": self.details,
            "run_id": run_id,
        }


class NotFoundError(AppError):
    status_code = 404
    code = "NOT_FOUND"


class UnauthorizedError(AppError):
    status_code = 401
    code = "UNAUTHORIZED"


class ForbiddenError(AppError):
    status_code = 403
    code = "FORBIDDEN"


class ValidationError(AppError):
    status_code = 422
    code = "VALIDATION_ERROR"


class VersionConflictError(AppError):
    status_code = 409
    code = "VERSION_CONFLICT"


class StaleDraftError(AppError):
    status_code = 409
    code = "STALE_DRAFT"


class SourceMissingError(AppError):
    status_code = 422
    code = "SOURCE_MISSING"


class SourceConflictError(AppError):
    status_code = 409
    code = "SOURCE_CONFLICT"


class UnknownProductError(AppError):
    status_code = 422
    code = "UNKNOWN_PRODUCT"


class ImportFailedError(AppError):
    status_code = 422
    code = "IMPORT_FAILED"


class ModelUnavailableError(AppError):
    status_code = 503
    code = "MODEL_UNAVAILABLE"
    retryable = True


class InvalidModelOutputError(AppError):
    status_code = 502
    code = "INVALID_MODEL_OUTPUT"
    retryable = True


class EnvironmentUnavailableError(AppError):
    status_code = 503
    code = "ENVIRONMENT_UNAVAILABLE"
    retryable = True


class RateLimitedError(AppError):
    status_code = 429
    code = "RATE_LIMITED"
    retryable = True


class NotConfiguredError(AppError):
    status_code = 501
    code = "NOT_CONFIGURED"


def not_found(entity: str) -> NotFoundError:
    """Opaque 404 used for both missing and cross-owner resources."""
    return NotFoundError(f"{entity}不存在或无权访问")
