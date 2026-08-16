"""Thin views for the dashboards app.

Eight endpoints, one per section, all shaped identically: check access, validate
the shared filter set, call one composition selector, return the standard
envelope. No business logic, no queries.

**Why eight endpoints and not one.** Every section is independently useful and
independently slow. A single aggregate would make the whole page wait on its
worst query, give the whole page one permission key and one risk level, and
force a full refetch to update one panel. Splitting them costs a client a few
parallel requests and buys a screen where a slow section cannot block the rest
(``concepts/dashboards.txt`` — "Recommended layout").
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from core.pagination import StandardPagination
from core.responses import error_response, success_response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from dashboards import selectors
from dashboards.access import require_activity_reader, require_dashboard_actor
from dashboards.constants import ErrorCode
from dashboards.exceptions import ActorNotPermittedError
from dashboards.serializers import ActivityRowSerializer, DashboardFilterSerializer


def _forbidden() -> Response:
    return error_response(
        ErrorCode.ACTOR_FORBIDDEN,
        "Your authority level may not read the dashboard.",
        http_status=status.HTTP_403_FORBIDDEN,
    )


class DashboardSectionView(APIView):
    """Base for every section endpoint.

    Subclasses supply ``section``; everything else — the access check, filter
    validation, and the response envelope — is identical by construction, which
    is what keeps the eight sections answering the same filter set the same way.
    """

    permission_classes = [IsAuthenticated]

    #: The composition selector this endpoint returns. Set by each subclass.
    section: Callable[..., Any]

    #: The ``message`` on a successful response.
    message: str = "Dashboard section retrieved."

    def resolve(self, request: Request) -> tuple[dict[str, Any] | None, Response | None]:
        """Authorise the caller and validate the filters, or return a response."""
        try:
            require_dashboard_actor(request.user)
        except ActorNotPermittedError:
            return None, _forbidden()

        serializer = DashboardFilterSerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        return serializer.to_filters(), None

    def get(self, request: Request) -> Response:
        filters, err = self.resolve(request)
        if err:
            return err
        data = type(self).section(actor=request.user, filters=filters)
        return success_response(data=data, message=self.message)


class DashboardSummaryView(DashboardSectionView):
    """GET /api/v1/dashboard/summary/ — top-line counts and alert totals."""

    section = staticmethod(selectors.get_summary)
    message = "Dashboard summary retrieved."


class DashboardTodayView(DashboardSectionView):
    """GET /api/v1/dashboard/today/ — overdue and due-soon work."""

    section = staticmethod(selectors.get_today)
    message = "Today's work retrieved."


class DashboardPipelineView(DashboardSectionView):
    """GET /api/v1/dashboard/pipeline/ — stage and status counts across the business."""

    section = staticmethod(selectors.get_pipeline)
    message = "Pipeline health retrieved."


class DashboardBlockersView(DashboardSectionView):
    """GET /api/v1/dashboard/blockers/ — risk surfaced before it becomes an outcome."""

    section = staticmethod(selectors.get_blockers)
    message = "Blockers retrieved."


class DashboardWorkloadView(DashboardSectionView):
    """GET /api/v1/dashboard/workload/ — how work is distributed across the team."""

    section = staticmethod(selectors.get_workload)
    message = "Workload retrieved."


class DashboardConversionView(DashboardSectionView):
    """GET /api/v1/dashboard/conversion/ — intake mix and stage-to-stage rates."""

    section = staticmethod(selectors.get_conversion)
    message = "Conversion retrieved."


class DashboardOutcomesView(DashboardSectionView):
    """GET /api/v1/dashboard/outcomes/ — how work ended over the window."""

    section = staticmethod(selectors.get_outcomes)
    message = "Outcomes retrieved."


class DashboardActivityView(DashboardSectionView):
    """GET /api/v1/dashboard/activity/ — the recent-activity feed.

    The one section returning a paginated list rather than an assembled object,
    because it genuinely is a list. Everything else on the dashboard summarizes
    many rows; this one *is* the rows.
    """

    section = staticmethod(selectors.get_activity)

    def resolve(self, request: Request) -> tuple[dict[str, Any] | None, Response | None]:
        """The dashboard rule, plus the audit log's own stricter one.

        This section returns rows from the central audit log rather than figures
        derived from an app that already scoped them, so it carries `audit`'s
        access rule as well as the dashboard's. Overridden here rather than
        checked inside ``get`` so the two authority checks cannot drift apart,
        and so any future verb added to this view inherits both.
        """
        filters, err = super().resolve(request)
        if err:
            return None, err
        try:
            require_activity_reader(request.user)
        except ActorNotPermittedError:
            return None, _forbidden()
        return filters, None

    def get(self, request: Request) -> Response:
        filters, err = self.resolve(request)
        if err:
            return err
        queryset = selectors.get_activity(actor=request.user, filters=filters)

        paginator = StandardPagination()
        page = paginator.paginate_queryset(queryset, request)
        serializer = ActivityRowSerializer(page if page is not None else queryset, many=True)
        if page is not None:
            return paginator.get_paginated_response(serializer.data)
        return success_response(data=serializer.data, message="Recent activity retrieved.")
