from typing import Any

from rest_framework import status
from rest_framework.response import Response


def success_response(
    data: Any = None,
    message: str = "",
    meta: dict | None = None,
    http_status: int = status.HTTP_200_OK,
) -> Response:
    return Response(
        {
            "success": True,
            "message": message,
            "data": data if data is not None else {},
            "meta": meta if meta is not None else {},
        },
        status=http_status,
    )


def error_response(
    code: str,
    message: str,
    details: dict | list | None = None,
    meta: dict | None = None,
    http_status: int = status.HTTP_400_BAD_REQUEST,
) -> Response:
    return Response(
        {
            "success": False,
            "error": {
                "code": code,
                "message": message,
                "details": details if details is not None else {},
            },
            "meta": meta if meta is not None else {},
        },
        status=http_status,
    )
