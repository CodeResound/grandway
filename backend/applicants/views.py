"""Thin views for the applicants app.

Views receive the request, apply the interim access checks (§9, ``access.py``),
validate input, call a service, translate domain exceptions into the standard
error envelope, and shape the response. No business logic lives here.
"""

from __future__ import annotations

from typing import Any

from audit.serializers import AuditEventHistorySerializer
from core.pagination import StandardPagination
from core.responses import error_response, success_response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from applicants import services
from applicants.access import require_admin, require_applicant_actor
from applicants.constants import ErrorCode
from applicants.exceptions import (
    ActorNotPermittedError,
    ContactNumberRequiredError,
    PassportExpiryInvalidError,
)
from applicants.models import Applicant
from applicants.selectors import (
    filter_applicants,
    get_applicant_by_id,
    get_applicants,
    get_history_for_applicant,
    rank_applicants,
)
from applicants.serializers import (
    ApplicantCreateSerializer,
    ApplicantDetailSerializer,
    ApplicantListFilterSerializer,
    ApplicantListSerializer,
    ApplicantUpdateSerializer,
    StatusChangeSerializer,
)

#: Nested collections pulled out of the applicant payload before it reaches the
#: service. Each replaces its set wholesale; the passport is upserted.
_NESTED_KEYS = ("contact_numbers", "addresses", "family_members", "emergency_contacts", "passport")


def _client_ip(request: Request) -> str | None:
    return request.META.get("REMOTE_ADDR")


def _forbidden() -> Response:
    return error_response(
        ErrorCode.ACTOR_FORBIDDEN,
        "Your authority level may not perform this action.",
        http_status=status.HTTP_403_FORBIDDEN,
    )


def _not_found() -> Response:
    return error_response(
        ErrorCode.APPLICANT_NOT_FOUND,
        "Applicant not found.",
        http_status=status.HTTP_404_NOT_FOUND,
    )


def _split_nested(validated: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Separate scalar applicant fields from the nested sub-resource payloads."""
    nested = {key: validated.pop(key) for key in _NESTED_KEYS if key in validated}
    return validated, nested


def _paginated(request: Request, queryset: Any, serializer_class: Any, message: str) -> Response:
    paginator = StandardPagination()
    page = paginator.paginate_queryset(queryset, request)
    serializer = serializer_class(page if page is not None else queryset, many=True)
    if page is not None:
        return paginator.get_paginated_response(serializer.data)
    return success_response(data=serializer.data, message=message)


class ApplicantScopedView(APIView):
    """Base for every view addressing a single applicant by id."""

    permission_classes = [IsAuthenticated]

    def resolve(self, request: Request, applicant_id: str) -> tuple[Applicant | None, Response | None]:
        try:
            require_applicant_actor(request.user)
        except ActorNotPermittedError:
            return None, _forbidden()
        applicant = get_applicant_by_id(applicant_id)
        if applicant is None:
            return None, _not_found()
        return applicant, None


class ApplicantListCreateView(APIView):
    """GET/POST /api/v1/applicants/ — list every applicant, or create one directly."""

    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        try:
            require_applicant_actor(request.user)
        except ActorNotPermittedError:
            return _forbidden()
        filter_serializer = ApplicantListFilterSerializer(data=request.query_params)
        filter_serializer.is_valid(raise_exception=True)
        filters = dict(filter_serializer.validated_data)
        search = filters.get("search")
        queryset = filter_applicants(get_applicants(), filters)
        # Relevance ordering applies only when there is a query to be relevant
        # to; an unsearched list keeps the model's newest-first ordering.
        if search:
            queryset = rank_applicants(queryset, search)
        return _paginated(request, queryset, ApplicantListSerializer, "Applicants retrieved.")

    def post(self, request: Request) -> Response:
        # Direct creation is Admin-only: Lead Managers work leads, and entry
        # into the applicant lifecycle is an Admin decision.
        try:
            require_admin(request.user)
        except ActorNotPermittedError:
            return _forbidden()

        serializer = ApplicantCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data, nested = _split_nested(dict(serializer.validated_data))

        try:
            applicant = services.create_applicant(
                actor=request.user,
                data=data,
                contact_numbers=nested["contact_numbers"],
                addresses=nested.get("addresses"),
                family_members=nested.get("family_members"),
                emergency_contacts=nested.get("emergency_contacts"),
                passport=nested.get("passport"),
                ip_address=_client_ip(request),
            )
        except ContactNumberRequiredError:
            return error_response(
                ErrorCode.CONTACT_REQUIRED,
                "An applicant needs at least one contact number.",
                http_status=status.HTTP_400_BAD_REQUEST,
            )
        except PassportExpiryInvalidError:
            return error_response(
                ErrorCode.PASSPORT_EXPIRY_INVALID,
                "Passport expiry must fall after its issue date.",
                details={"passport": {"expiry_date": ["Must be later than the issue date."]}},
                http_status=status.HTTP_400_BAD_REQUEST,
            )
        return success_response(
            data=ApplicantDetailSerializer(applicant).data,
            message="Applicant created.",
            http_status=status.HTTP_201_CREATED,
        )


class ApplicantDetailView(ApplicantScopedView):
    """GET/PATCH /api/v1/applicants/<id>/ — read or correct an applicant."""

    def get(self, request: Request, applicant_id: str) -> Response:
        applicant, err = self.resolve(request, applicant_id)
        if err:
            return err
        return success_response(
            data=ApplicantDetailSerializer(applicant).data,
            message="Applicant retrieved.",
        )

    def patch(self, request: Request, applicant_id: str) -> Response:
        applicant, err = self.resolve(request, applicant_id)
        if err:
            return err
        serializer = ApplicantUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        fields, nested = _split_nested(dict(serializer.validated_data))

        try:
            updated = services.update_applicant(
                actor=request.user,
                applicant=applicant,
                fields=fields,
                contact_numbers=nested.get("contact_numbers"),
                addresses=nested.get("addresses"),
                family_members=nested.get("family_members"),
                emergency_contacts=nested.get("emergency_contacts"),
                passport=nested.get("passport"),
                ip_address=_client_ip(request),
            )
        except ContactNumberRequiredError:
            return error_response(
                ErrorCode.CONTACT_REQUIRED,
                "An applicant needs at least one contact number.",
                http_status=status.HTTP_400_BAD_REQUEST,
            )
        except PassportExpiryInvalidError:
            return error_response(
                ErrorCode.PASSPORT_EXPIRY_INVALID,
                "Passport expiry must fall after its issue date.",
                details={"passport": {"expiry_date": ["Must be later than the issue date."]}},
                http_status=status.HTTP_400_BAD_REQUEST,
            )
        # Re-read so the response carries the freshly replaced nested collections.
        return success_response(
            data=ApplicantDetailSerializer(get_applicant_by_id(str(updated.id))).data,
            message="Applicant updated.",
        )


class ApplicantStatusView(ApplicantScopedView):
    """POST /api/v1/applicants/<id>/status/ — set the applicant's standing."""

    def post(self, request: Request, applicant_id: str) -> Response:
        applicant, err = self.resolve(request, applicant_id)
        if err:
            return err
        serializer = StatusChangeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        updated = services.change_status(
            actor=request.user,
            applicant=applicant,
            status=serializer.validated_data["status"],
            ip_address=_client_ip(request),
        )
        return success_response(
            data=ApplicantDetailSerializer(updated).data,
            message="Applicant status updated.",
        )


class ApplicantHistoryView(ApplicantScopedView):
    """GET /api/v1/applicants/<id>/history/ — the applicant's chronological history."""

    def get(self, request: Request, applicant_id: str) -> Response:
        applicant, err = self.resolve(request, applicant_id)
        if err:
            return err
        return _paginated(
            request,
            get_history_for_applicant(applicant),
            AuditEventHistorySerializer,
            "History retrieved.",
        )
