"""Thin views for the search app.

Two endpoints: the query, and the catalogue of what can be queried. Both are
shaped the way every view in this project is — check access, validate input,
call one selector, return the standard envelope. No business logic, no queries.

**Why the catalogue is a second endpoint rather than a field on the first.**
A client needs the list of types before it has a query to send: the filter chips
render on an empty search box. Folding the catalogue into the query response
would mean either shipping it on every keystroke or hardcoding it in the client,
and the second is what ``concepts/search.txt`` asks this app to avoid.

**Why the query is not paginated.** It returns nine bounded buckets, not one
long list, and the standard page envelope describes a single sequence with a
next link. There is no coherent "page 2" of a grouped panel — page two of what,
across nine types with different totals? Depth belongs to the owning app's list
endpoint, which each bucket links to by ``list_url``.
"""

from __future__ import annotations

from core.responses import error_response, success_response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from search import selectors
from search.access import require_search_actor
from search.constants import ErrorCode
from search.exceptions import ActorNotPermittedError
from search.serializers import (
    SearchableTypeSerializer,
    SearchQuerySerializer,
    SearchResultSerializer,
)
from search.throttling import SearchThrottle


def _forbidden() -> Response:
    return error_response(
        ErrorCode.ACTOR_FORBIDDEN,
        "Your authority level may not use global search.",
        http_status=status.HTTP_403_FORBIDDEN,
    )


class GlobalSearchView(APIView):
    """GET /api/v1/search/ — one query, answered across every searchable type.

    The response is grouped by type rather than interleaved into one ranked
    list, because cross-type relevance is not comparable: an applicant's name
    score and an institution's name score are computed by different selectors on
    different scales, and ordering them against each other would produce a
    confident-looking sequence with nothing behind it (``concepts/search.txt`` —
    "Constraints").
    """

    permission_classes = [IsAuthenticated]
    throttle_classes = [SearchThrottle]

    def get(self, request: Request) -> Response:
        try:
            require_search_actor(request.user)
        except ActorNotPermittedError:
            return _forbidden()

        serializer = SearchQuerySerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)

        results = selectors.search_everything(actor=request.user, **serializer.to_params())
        return success_response(
            data=SearchResultSerializer(results).data,
            message="Search results retrieved.",
        )


class SearchableTypesView(APIView):
    """GET /api/v1/search/types/ — the catalogue of searchable record types.

    Static per deployment and cheap: it reads the catalogue in
    ``search/constants.py`` and touches no table. A client fetches it once at
    startup to build its filter chips and its result-routing table.

    No throttle scope of its own — it costs nothing, and the project-wide
    ``user`` rate is the right cap for it.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        try:
            require_search_actor(request.user)
        except ActorNotPermittedError:
            return _forbidden()

        types = selectors.get_searchable_types()
        return success_response(
            data=SearchableTypeSerializer(types, many=True).data,
            message="Searchable types retrieved.",
        )
