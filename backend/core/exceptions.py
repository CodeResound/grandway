import logging

from rest_framework import status
from rest_framework.exceptions import (
    AuthenticationFailed,
    MethodNotAllowed,
    NotAuthenticated,
    NotFound,
    PermissionDenied,
    Throttled,
    ValidationError,
)
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler

from core.constants import ErrorCode

logger = logging.getLogger(__name__)

_EXCEPTION_MAP: dict[type, tuple[str, int]] = {
    NotAuthenticated: (ErrorCode.AUTHENTICATION_REQUIRED, status.HTTP_401_UNAUTHORIZED),
    AuthenticationFailed: (ErrorCode.AUTHENTICATION_FAILED, status.HTTP_401_UNAUTHORIZED),
    PermissionDenied: (ErrorCode.PERMISSION_DENIED, status.HTTP_403_FORBIDDEN),
    NotFound: (ErrorCode.NOT_FOUND, status.HTTP_404_NOT_FOUND),
    MethodNotAllowed: (ErrorCode.METHOD_NOT_ALLOWED, status.HTTP_405_METHOD_NOT_ALLOWED),
    Throttled: (ErrorCode.RATE_LIMIT_EXCEEDED, status.HTTP_429_TOO_MANY_REQUESTS),
}


def _error_response(code: str, message: str, details: dict | list, http_status: int) -> Response:
    return Response(
        {
            "success": False,
            "error": {
                "code": code,
                "message": message,
                "details": details,
            },
            "meta": {},
        },
        status=http_status,
    )


def global_exception_handler(exc: Exception, context: dict) -> Response:
    response = drf_exception_handler(exc, context)

    if response is None:
        logger.exception("Unhandled server error", extra={"exception": str(exc)})
        return _error_response(
            code=ErrorCode.INTERNAL_SERVER_ERROR,
            message="An unexpected error occurred.",
            details={},
            http_status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    if isinstance(exc, ValidationError):
        return _error_response(
            code=ErrorCode.VALIDATION_ERROR,
            message="Validation failed.",
            details=exc.detail,
            http_status=status.HTTP_400_BAD_REQUEST,
        )

    for exc_class, (code, http_status) in _EXCEPTION_MAP.items():
        if isinstance(exc, exc_class):
            detail = exc.detail if hasattr(exc, "detail") else str(exc)
            message = detail if isinstance(detail, str) else str(detail)
            return _error_response(
                code=code,
                message=message,
                details={},
                http_status=http_status,
            )

    return _error_response(
        code="ERROR",
        message=str(getattr(exc, "detail", exc)),
        details={},
        http_status=response.status_code,
    )
