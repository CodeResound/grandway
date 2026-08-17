"""Client-address resolution shared by every app that records request IPs (§2).

DRF's throttles and django-axes already resolve "the client's address" through
``NUM_PROXIES``; audit surfaces (auth events, session rows, file-download
records) previously read ``REMOTE_ADDR`` raw, so behind a TLS-terminating
proxy every row recorded the proxy instead of the client (2026-08-17 security
audit, S7). One resolver keeps all three surfaces telling the same story.
"""

from __future__ import annotations

from django.http import HttpRequest
from rest_framework.settings import api_settings


def client_ip(request: HttpRequest) -> str | None:
    """The address DRF's throttles would attribute this request to.

    Mirrors ``rest_framework.throttling.BaseThrottle.get_ident``: with
    ``NUM_PROXIES=0`` (the default) ``X-Forwarded-For`` is client-forgeable
    noise and is ignored; with ``N > 0`` the address ``N`` hops from the right
    of ``X-Forwarded-For`` is the first one a trusted proxy wrote.
    """
    num_proxies = api_settings.NUM_PROXIES
    remote_addr = request.META.get("REMOTE_ADDR")
    forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
    if not num_proxies or not forwarded_for:
        return remote_addr
    addrs = forwarded_for.split(",")
    return addrs[-min(num_proxies, len(addrs))].strip()
