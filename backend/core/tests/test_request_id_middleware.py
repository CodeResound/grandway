"""The correlation id is client-supplied, and therefore untrusted.

``RequestIDMiddleware`` accepts an ``X-Request-ID`` header so a request can be
traced across services, and that value ends up in two places that punish
unvalidated input:

* the log line built by ``core.logging.StructuredFormatter``, which is a
  space-delimited ``key=value`` format — so a header of
  ``1 logger=django msg=login succeeded`` forges fields in a machine-readable
  log without needing a newline at all (CWE-117, log injection);
* the ``X-Request-ID`` response header, echoed straight back.

These tests pin the rule that closes both: a supplied id is used only when it
looks like a correlation id, and anything else is replaced with a fresh UUID
rather than rejected — tracing is a convenience, and an unusable header must not
fail the request.
"""

from __future__ import annotations

import uuid

from django.http import HttpResponse
from django.test import RequestFactory, TestCase

from core.middleware import RequestIDMiddleware, get_request_id


def _run(**headers: str) -> tuple[HttpResponse, str]:
    """Send one request through the middleware; return (response, id seen inside)."""
    seen: dict[str, str] = {}

    def view(request):  # noqa: ANN001, ANN202 — a stub, not project code
        seen["id"] = get_request_id()
        return HttpResponse("ok")

    request = RequestFactory().get("/", **headers)
    response = RequestIDMiddleware(view)(request)
    return response, seen["id"]


class RequestIDValidationTests(TestCase):
    def test_well_formed_id_is_honoured(self) -> None:
        supplied = "0f8d4c1e-2b3a-4c5d-8e9f-a0b1c2d3e4f5"
        response, inside = _run(HTTP_X_REQUEST_ID=supplied)
        self.assertEqual(response["X-Request-ID"], supplied)
        self.assertEqual(inside, supplied)

    def test_absent_header_gets_a_fresh_uuid(self) -> None:
        response, inside = _run()
        self.assertEqual(response["X-Request-ID"], inside)
        uuid.UUID(inside)  # raises if it is not a UUID

    def test_log_forging_payload_is_discarded(self) -> None:
        """A value carrying the log format's own delimiters never reaches a log."""
        response, inside = _run(HTTP_X_REQUEST_ID="1 logger=django msg=admin login succeeded")
        self.assertNotIn(" ", inside)
        self.assertNotIn("logger=", inside)
        uuid.UUID(inside)
        self.assertEqual(response["X-Request-ID"], inside)

    def test_over_long_id_is_discarded(self) -> None:
        """An 8 KB header must not be repeated on every log line of the request."""
        _response, inside = _run(HTTP_X_REQUEST_ID="a" * 8192)
        self.assertLessEqual(len(inside), 64)
        uuid.UUID(inside)

    def test_empty_header_gets_a_fresh_uuid(self) -> None:
        _response, inside = _run(HTTP_X_REQUEST_ID="")
        uuid.UUID(inside)

    def test_id_does_not_leak_into_the_next_request(self) -> None:
        """A pooled worker thread must not carry a stale correlation id.

        A wrong correlation is worse than a missing one: it silently attributes
        one request's log lines to another.
        """
        _run(HTTP_X_REQUEST_ID="first-request-id")
        self.assertEqual(get_request_id(), "unknown")
