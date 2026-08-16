import re
import threading
import uuid
from collections.abc import Callable

from django.http import HttpRequest, HttpResponse

_local = threading.local()

#: What an inbound ``X-Request-ID`` may contain to be trusted and echoed back.
#:
#: The header is client-controlled and ends up in two places that both punish
#: unvalidated input: the ``key=value`` log line built by
#: ``core.logging.StructuredFormatter``, and the ``X-Request-ID`` response
#: header. A value like ``1 logger=django msg=login succeeded`` would forge
#: fields in a machine-readable log (CWE-117) without needing a newline at all,
#: because the format is space-delimited. Restricting the character set to what
#: a correlation id actually needs — the shape of a UUID, a ULID, or a trace id
#: — removes the whole class of problem rather than escaping one instance of it.
#:
#: A rejected value is not an error: the header is a convenience for tracing a
#: request across services, so an unusable one is replaced with a fresh UUID and
#: the request proceeds.
_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


def _resolve_request_id(request: HttpRequest) -> str:
    """The caller's correlation id when it is safe to use, else a fresh UUID."""
    supplied = request.META.get("HTTP_X_REQUEST_ID", "")
    if supplied and _REQUEST_ID_PATTERN.match(supplied):
        return supplied
    return str(uuid.uuid4())


class RequestIDMiddleware:
    def __init__(self, get_response: Callable) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        request_id = _resolve_request_id(request)
        request.request_id = request_id  # type: ignore[attr-defined]
        _local.request_id = request_id
        try:
            response = self.get_response(request)
        finally:
            # Cleared on the way out so a pooled worker thread can never carry
            # one request's id into the next request's logs — a stale id is a
            # correlation that is wrong rather than missing.
            _local.request_id = None
        response["X-Request-ID"] = request_id
        return response


def get_request_id() -> str:
    """The current request's correlation id, or ``"unknown"`` outside a request.

    ``or`` rather than a ``getattr`` default: the middleware clears the slot to
    ``None`` on the way out, so the attribute exists between requests and a
    default alone would never be reached.
    """
    return getattr(_local, "request_id", None) or "unknown"
