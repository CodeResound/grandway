"""Thin read-only views for the audit app.

Audit is read-only over HTTP — events are written only through the service call
from other apps. Read access is Admin/Superadmin (interim `is_staff` check, §9).
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Any

from core.pagination import StandardPagination
from core.responses import error_response, success_response
from rest_framework import status
from rest_framework.exceptions import NotAuthenticated, PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from audit.constants import DATE_FILTER_FORMAT, ORDER_CHOICES, SEARCH_MIN_LENGTH, ErrorCode
from audit.selectors import get_event_by_id, get_event_facets, get_events
from audit.serializers import AuditEventSerializer, AuditFacetsSerializer

_FISCAL_YEAR_RE = re.compile(r"^\d{4}/\d{2}$")


def _require_staff(request: Request) -> None:
    """Interim access check (§9): audit read is Admin/Superadmin only."""
    if not request.user.is_authenticated:
        raise NotAuthenticated("Authentication required.")
    if not request.user.is_staff:
        raise PermissionDenied("Audit access is restricted to administrators.")


def _clean_filters(params: Any) -> dict[str, Any]:
    """Validate and normalise list filters (AND-combined).

    Most filters are exact-match; `search` is a substring match on `summary`,
    `date_from`/`date_to` bound a range of NPT calendar days, and `order`
    chooses the sort direction. Malformed values raise a DRF ValidationError →
    `VALIDATION_ERROR` (400) rather than a 500. `?app=` maps to `app_label`.
    """
    cleaned: dict[str, Any] = {}
    errors: dict[str, list[str]] = {}

    for key in ("app", "action", "actor_type", "entity_type"):
        value = params.get(key)
        if value:
            cleaned[key] = value

    for key in ("actor_id", "entity_id"):
        value = params.get(key)
        if value:
            try:
                uuid.UUID(value)
                cleaned[key] = value
            except (ValueError, AttributeError, TypeError):
                errors[key] = ["Must be a valid UUID."]

    success = params.get("success")
    if success:
        low = success.lower()
        if low in ("true", "1"):
            cleaned["success"] = True
        elif low in ("false", "0"):
            cleaned["success"] = False
        else:
            errors["success"] = ["Must be 'true' or 'false'."]

    fiscal_year = params.get("fiscal_year")
    if fiscal_year:
        if not _FISCAL_YEAR_RE.match(fiscal_year):
            errors["fiscal_year"] = ["Must be in YYYY/YY form, e.g. 2082/83."]
        else:
            from core.nepal.calendar import fiscal_year_gregorian_range

            try:
                fiscal_year_gregorian_range(fiscal_year)
                cleaned["fiscal_year"] = fiscal_year
            except Exception:  # noqa: BLE001 — any calendar error is a bad filter value
                errors["fiscal_year"] = ["Not a valid fiscal year."]

    search = params.get("search")
    if search:
        term = search.strip()
        if len(term) < SEARCH_MIN_LENGTH:
            errors["search"] = [f"Must be at least {SEARCH_MIN_LENGTH} characters."]
        else:
            cleaned["search"] = term

    for key in ("date_from", "date_to"):
        value = params.get(key)
        if value:
            try:
                cleaned[key] = datetime.strptime(value, DATE_FILTER_FORMAT).date()
            except (ValueError, TypeError):
                errors[key] = ["Must be a date in YYYY-MM-DD form."]

    if "date_from" in cleaned and "date_to" in cleaned and cleaned["date_from"] > cleaned["date_to"]:
        # Reported rather than silently swapped: an inverted range is a caller
        # bug, and returning zero rows for it reads as "nothing happened".
        errors["date_to"] = ["Must not be earlier than date_from."]

    order = params.get("order")
    if order:
        low = order.lower()
        if low not in ORDER_CHOICES:
            errors["order"] = [f"Must be one of: {', '.join(ORDER_CHOICES)}."]
        else:
            cleaned["order"] = low

    if errors:
        raise ValidationError(errors)
    return cleaned


class AuditEventListView(APIView):
    """GET /api/v1/audit/events/ — list/filter audit events (paginated)."""

    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        _require_staff(request)
        filters = _clean_filters(request.query_params)
        events = get_events(filters)
        paginator = StandardPagination()
        page = paginator.paginate_queryset(events, request)
        serializer = AuditEventSerializer(page if page is not None else events, many=True)
        if page is not None:
            return paginator.get_paginated_response(serializer.data)
        return success_response(data=serializer.data, message="Audit events retrieved.")


class AuditEventFacetsView(APIView):
    """GET /api/v1/audit/events/facets/ — distinct filter values for the log UI."""

    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        _require_staff(request)
        serializer = AuditFacetsSerializer(get_event_facets())
        return success_response(data=serializer.data, message="Audit filter values retrieved.")


class AuditEventDetailView(APIView):
    """GET /api/v1/audit/events/<id>/ — one audit event."""

    permission_classes = [IsAuthenticated]

    def get(self, request: Request, event_id: str) -> Response:
        _require_staff(request)
        event = get_event_by_id(event_id)
        if event is None:
            return error_response(
                ErrorCode.EVENT_NOT_FOUND,
                "Audit event not found.",
                http_status=status.HTTP_404_NOT_FOUND,
            )
        return success_response(data=AuditEventSerializer(event).data, message="Audit event retrieved.")
