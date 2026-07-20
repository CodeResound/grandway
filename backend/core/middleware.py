import threading
import uuid
from collections.abc import Callable

from django.http import HttpRequest, HttpResponse

_local = threading.local()


class RequestIDMiddleware:
    def __init__(self, get_response: Callable) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        request_id = request.META.get("HTTP_X_REQUEST_ID", str(uuid.uuid4()))
        request.request_id = request_id  # type: ignore[attr-defined]
        _local.request_id = request_id
        response = self.get_response(request)
        response["X-Request-ID"] = request_id
        return response


def get_request_id() -> str:
    return getattr(_local, "request_id", "unknown")
