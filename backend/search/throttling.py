"""Scoped rate throttle for the global search endpoint.

Rates live in ``settings.REST_FRAMEWORK['DEFAULT_THROTTLE_RATES']``, following
the pattern ``authenticate/throttling.py`` established.

**Why this endpoint needs its own cap when list endpoints do not.** One search
is up to nine queries and nine counts across seven apps — an order of magnitude
more work per request than any list view — and it is the one endpoint a user
drives keystroke by keystroke. A search-as-you-type box with no debounce would
spend the project-wide ``user`` budget of 1000/hour in a few minutes of normal
typing, and the user would then be throttled out of the *whole API*, not just
out of search. A scope of its own contains that: search gets its own bucket, and
exhausting it never blocks the record the user was trying to open.

Per-user rather than per-IP, unlike the authenticate throttles. Those cap
attempts against credentials that have not been checked yet, so the IP is the
only identity available; here the caller is authenticated, and an office of ten
staff sharing one office IP must not share one search budget.
"""

from __future__ import annotations

from typing import Any

from rest_framework.throttling import SimpleRateThrottle

from search.constants import THROTTLE_SCOPE_SEARCH


class SearchThrottle(SimpleRateThrottle):
    """Per-user cap on global search queries."""

    scope = THROTTLE_SCOPE_SEARCH

    def get_cache_key(self, request: Any, view: Any) -> str | None:
        """Key on the authenticated user; fall back to IP for anyone else.

        The anonymous branch is unreachable through the URL conf — the view
        requires authentication — but returning ``None`` there would silently
        disable the throttle if that ever changed, and a throttle that fails
        open is worse than no throttle, because it reads as protection.
        """
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated:
            ident = str(user.pk)
        else:
            ident = self.get_ident(request)
        return self.cache_format % {"scope": self.scope, "ident": ident}
