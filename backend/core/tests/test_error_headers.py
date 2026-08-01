"""Regression test: the standard error envelope must not eat protocol headers.

``global_exception_handler`` replaces DRF's response with a standard-envelope
one. DRF builds two headers alongside that response which belong to the HTTP
exchange rather than to the body, and rebuilding the response without them
dropped both:

* ``WWW-Authenticate`` on a 401 — RFC 7235 requires it on every 401, and it is
  how a client learns which scheme to authenticate with.
* ``Retry-After`` on a 429 — without it a throttled client can only guess, and
  guessing wrong is what turns a rate limit into a retry storm.
"""

from __future__ import annotations

from rest_framework import status
from rest_framework.exceptions import NotAuthenticated, Throttled
from rest_framework.test import APIRequestFactory

from core.exceptions import global_exception_handler


def _handle(exc):
    request = APIRequestFactory().get("/api/v1/anything/")
    return global_exception_handler(exc, {"request": request, "view": None})


def test_throttled_response_carries_retry_after():
    response = _handle(Throttled(wait=42))

    assert response.status_code == status.HTTP_429_TOO_MANY_REQUESTS
    assert response.headers["Retry-After"] == "42"
    # The envelope is still the project's standard one.
    assert response.data["success"] is False


def test_unauthenticated_response_carries_www_authenticate():
    exc = NotAuthenticated()
    exc.auth_header = 'Bearer realm="api"'

    response = _handle(exc)

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert response.headers["WWW-Authenticate"] == 'Bearer realm="api"'


def test_an_exception_without_protocol_headers_adds_none():
    response = _handle(NotAuthenticated())

    assert "WWW-Authenticate" not in response.headers
    assert "Retry-After" not in response.headers
