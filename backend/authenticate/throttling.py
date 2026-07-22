"""Scoped rate throttles for the authenticate endpoints.

Rates live in ``settings.REST_FRAMEWORK['DEFAULT_THROTTLE_RATES']``. These
complement django-axes (which does the stateful lockout); throttling caps burst
rate per IP and per submitted username before credentials are even checked.
"""

from __future__ import annotations

from typing import Any

from rest_framework.throttling import SimpleRateThrottle

from authenticate.constants import (
    THROTTLE_SCOPE_LOGIN_IP,
    THROTTLE_SCOPE_LOGIN_USER,
    THROTTLE_SCOPE_REFRESH,
)
from authenticate.managers import UserManager


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
    """Per-IP cap on refresh calls."""

    scope = THROTTLE_SCOPE_REFRESH

    def get_cache_key(self, request: Any, view: Any) -> str | None:
        return self.cache_format % {"scope": self.scope, "ident": self.get_ident(request)}
