"""Scoped rate throttles for the authenticate endpoints.

Rates live in ``settings.REST_FRAMEWORK['DEFAULT_THROTTLE_RATES']``. These
complement django-axes (which does the stateful lockout); throttling caps burst
rate per IP and per submitted username before credentials are even checked.
"""

from __future__ import annotations

from typing import Any

from django.conf import settings
from rest_framework.throttling import SimpleRateThrottle

from authenticate.constants import (
    THROTTLE_SCOPE_LOGIN_IP,
    THROTTLE_SCOPE_LOGIN_USER,
    THROTTLE_SCOPE_REFRESH,
    THROTTLE_SCOPE_REFRESH_TOKEN,
)
from authenticate.managers import UserManager
from authenticate.services import hash_refresh_token


class LoginIPThrottle(SimpleRateThrottle):
    """Per-IP cap on login attempts."""

    scope = THROTTLE_SCOPE_LOGIN_IP

    def get_cache_key(self, request: Any, view: Any) -> str | None:
        return self.cache_format % {"scope": self.scope, "ident": self.get_ident(request)}


class LoginUsernameThrottle(SimpleRateThrottle):
    """Per-username cap on login attempts (mitigates targeting one account)."""

    scope = THROTTLE_SCOPE_LOGIN_USER

    def get_cache_key(self, request: Any, view: Any) -> str | None:
        username = UserManager.normalize_username(request.data.get("username", ""))
        if not username:
            return None
        return self.cache_format % {"scope": self.scope, "ident": username}


class RefreshThrottle(SimpleRateThrottle):
    """Per-IP ceiling on refresh calls.

    Set well above one office's needs: everyone behind a shared public IP lands
    in this one bucket. Per-session limiting is ``RefreshTokenThrottle``'s job.
    """

    scope = THROTTLE_SCOPE_REFRESH

    def get_cache_key(self, request: Any, view: Any) -> str | None:
        return self.cache_format % {"scope": self.scope, "ident": self.get_ident(request)}


class RefreshTokenThrottle(SimpleRateThrottle):
    """Per-credential cap on refresh calls, keyed on the presented token's hash.

    Gives each session its own bucket, so a busy colleague on the same office IP
    cannot throttle anyone else out of refreshing. It cannot replace the per-IP
    ceiling: a client spraying random tokens lands in a fresh bucket each time.
    """

    scope = THROTTLE_SCOPE_REFRESH_TOKEN

    def get_cache_key(self, request: Any, view: Any) -> str | None:
        if settings.AUTH_REFRESH_COOKIE_ENABLED:
            raw_token = request.COOKIES.get(settings.AUTH_REFRESH_COOKIE_NAME, "")
        else:
            data = request.data
            raw_token = data.get("refresh", "") if hasattr(data, "get") else ""
        if not raw_token or not isinstance(raw_token, str):
            return None
        return self.cache_format % {"scope": self.scope, "ident": hash_refresh_token(raw_token)}
