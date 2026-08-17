"""Thin views for the applicant_journeys app.

Views receive the request, apply the interim access checks (§9, ``access.py``),
validate input, call a service, translate domain exceptions into the standard
error envelope, and shape the response. No business logic lives here.
"""

from __future__ import annotations

from typing import Any

from applicants.selectors import get_applicant_by_id
from audit.serializers import AuditEventHistorySerializer
from core.pagination import StandardPagination
from core.responses import error_response, success_response
from institutions.selectors import get_country_by_id
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from applicant_journeys import services
from applicant_journeys.access import require_journey_actor
from applicant_journeys.constants import ErrorCode
from applicant_journeys.exceptions import (
    ActorNotPermittedError,
    DeferIntakeRequiredError,
    InvalidStageTransitionError,
    JourneyNotTerminalError,
    OutcomeDetailRequiredError,
    OutcomeRequiredError,
    StageNotEditableError,
)
from applicant_journeys.models import ApplicantJourney
from applicant_journeys.selectors import (
    filter_journeys,
    get_history_for_journey,
    get_journey_by_id,
    get_journeys,
)
from applicant_journeys.serializers import (
    CloseSerializer,
    DeferSerializer,
    JourneyCreateSerializer,
    JourneyDetailSerializer,
    JourneyListFilterSerializer,
    JourneyListSerializer,
    JourneyUpdateSerializer,
    ReopenSerializer,
    StageChangeSerializer,
)


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
        ErrorCode.JOURNEY_NOT_FOUND,
        "Journey not found.",
        http_status=status.HTTP_404_NOT_FOUND,
    )


def _stage_not_editable() -> Response:
    return error_response(
        ErrorCode.STAGE_NOT_EDITABLE,
        "This journey is completed, closed, or deferred; reopen it first.",
        http_status=status.HTTP_409_CONFLICT,
    )


def _invalid_transition() -> Response:
    return error_response(
        ErrorCode.STAGE_INVALID_TRANSITION,
        "This stage cannot be selected directly; use the close or defer action.",
        http_status=status.HTTP_400_BAD_REQUEST,
    )


def _resolve_country(data: dict[str, Any]) -> Response | None:
    """Swap a ``target_country_ref`` id in ``data`` for the catalogue row itself.

    Mutates ``data`` in place and returns an error response when the id names no
    country. An explicit ``null`` clears the reference and is left as ``None``.

    Written once and called from both create and update so a client cannot learn
    one error code from ``POST`` and a different one from ``PATCH`` for the same
    bad id.
    """
    if "target_country_ref" not in data:
        return None
    country_id = data["target_country_ref"]
    if country_id is None:
        return None
    country = get_country_by_id(str(country_id))
    if country is None:
        return error_response(
            ErrorCode.COUNTRY_NOT_FOUND,
            "Country not found in the catalogue.",
            details={"target_country_ref": ["No country with that id."]},
            http_status=status.HTTP_400_BAD_REQUEST,
        )
    data["target_country_ref"] = country
    return None


def _paginated(request: Request, queryset: Any, serializer_class: Any, message: str) -> Response:
    paginator = StandardPagination()
    page = paginator.paginate_queryset(queryset, request)
    serializer = serializer_class(page if page is not None else queryset, many=True)
    if page is not None:
        return paginator.get_paginated_response(serializer.data)
    return success_response(data=serializer.data, message=message)


class JourneyScopedView(APIView):
    """Base for every view addressing a single journey by id."""

    permission_classes = [IsAuthenticated]

    def resolve(self, request: Request, journey_id: str) -> tuple[ApplicantJourney | None, Response | None]:
        try:
            require_journey_actor(request.user)
        except ActorNotPermittedError:
            return None, _forbidden()
        journey = get_journey_by_id(journey_id)
        if journey is None:
            return None, _not_found()
        return journey, None


class JourneyListCreateView(APIView):
    """GET/POST /api/v1/journeys/ — list journeys, or record a new objective."""

    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        try:
            require_journey_actor(request.user)
        except ActorNotPermittedError:
            return _forbidden()
        filter_serializer = JourneyListFilterSerializer(data=request.query_params)
        filter_serializer.is_valid(raise_exception=True)
        queryset = filter_journeys(get_journeys(), dict(filter_serializer.validated_data))
        return _paginated(request, queryset, JourneyListSerializer, "Journeys retrieved.")

    def post(self, request: Request) -> Response:
        try:
            require_journey_actor(request.user)
        except ActorNotPermittedError:
            return _forbidden()
        serializer = JourneyCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)

        applicant = get_applicant_by_id(str(data.pop("applicant")))
        if applicant is None:
            return error_response(
                ErrorCode.APPLICANT_NOT_FOUND,
                "Applicant not found.",
                details={"applicant": ["No applicant with that id."]},
                http_status=status.HTTP_400_BAD_REQUEST,
            )

        err = _resolve_country(data)
        if err:
            return err

        journey = services.create_journey(
            actor=request.user,
            applicant=applicant,
            data=data,
            ip_address=_client_ip(request),
        )
        return success_response(
            data=JourneyDetailSerializer(journey).data,
            message="Journey created.",
            http_status=status.HTTP_201_CREATED,
        )


class JourneyDetailView(JourneyScopedView):
    """GET/PATCH /api/v1/journeys/<id>/ — read or correct a journey."""

    def get(self, request: Request, journey_id: str) -> Response:
        journey, err = self.resolve(request, journey_id)
        if err:
            return err
        return success_response(data=JourneyDetailSerializer(journey).data, message="Journey retrieved.")

    def patch(self, request: Request, journey_id: str) -> Response:
        journey, err = self.resolve(request, journey_id)
        if err:
            return err
        serializer = JourneyUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        fields = dict(serializer.validated_data)
        err = _resolve_country(fields)
        if err:
            return err
        updated = services.update_journey(
            actor=request.user,
            journey=journey,
            fields=fields,
            ip_address=_client_ip(request),
        )
        return success_response(data=JourneyDetailSerializer(updated).data, message="Journey updated.")


class JourneyStageView(JourneyScopedView):
    """POST /api/v1/journeys/<id>/stage/ — move between active stages."""

    def post(self, request: Request, journey_id: str) -> Response:
        journey, err = self.resolve(request, journey_id)
        if err:
            return err
        serializer = StageChangeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            updated = services.change_stage(
                actor=request.user,
                journey=journey,
                stage=serializer.validated_data["stage"],
                ip_address=_client_ip(request),
            )
        except StageNotEditableError:
            return _stage_not_editable()
        except InvalidStageTransitionError:
            return _invalid_transition()
        return success_response(data=JourneyDetailSerializer(updated).data, message="Stage updated.")


class JourneyDeferView(JourneyScopedView):
    """POST /api/v1/journeys/<id>/defer/ — pause a journey to a later intake."""

    def post(self, request: Request, journey_id: str) -> Response:
        journey, err = self.resolve(request, journey_id)
        if err:
            return err
        serializer = DeferSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            updated = services.defer_journey(
                actor=request.user,
                journey=journey,
                to_intake=data["to_intake"],
                reason=data.get("reason", ""),
                ip_address=_client_ip(request),
            )
        except StageNotEditableError:
            return _stage_not_editable()
        except DeferIntakeRequiredError:
            return error_response(
                ErrorCode.DEFER_INTAKE_REQUIRED,
                "Deferring requires the intake being deferred to.",
                details={"to_intake": ["This field is required."]},
                http_status=status.HTTP_400_BAD_REQUEST,
            )
        return success_response(data=JourneyDetailSerializer(updated).data, message="Journey deferred.")


class JourneyCloseView(JourneyScopedView):
    """POST /api/v1/journeys/<id>/close/ — end a journey, recording why."""

    def post(self, request: Request, journey_id: str) -> Response:
        journey, err = self.resolve(request, journey_id)
        if err:
            return err
        serializer = CloseSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            updated = services.close_journey(
                actor=request.user,
                journey=journey,
                outcome=data["outcome"],
                reason=data.get("reason", ""),
                ip_address=_client_ip(request),
            )
        except StageNotEditableError:
            return _stage_not_editable()
        except OutcomeRequiredError:
            return error_response(
                ErrorCode.OUTCOME_REQUIRED,
                "An outcome is required to close a journey.",
                details={"outcome": ["This field is required."]},
                http_status=status.HTTP_400_BAD_REQUEST,
            )
        except OutcomeDetailRequiredError:
            return error_response(
                ErrorCode.OUTCOME_DETAIL_REQUIRED,
                "The 'other' outcome requires an explanation.",
                details={"reason": ["This field is required for the selected outcome."]},
                http_status=status.HTTP_400_BAD_REQUEST,
            )
        return success_response(data=JourneyDetailSerializer(updated).data, message="Journey closed.")


class JourneyReopenView(JourneyScopedView):
    """POST /api/v1/journeys/<id>/reopen/ — return a journey to active work."""

    def post(self, request: Request, journey_id: str) -> Response:
        journey, err = self.resolve(request, journey_id)
        if err:
            return err
        serializer = ReopenSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            updated = services.reopen_journey(
                actor=request.user,
                journey=journey,
                stage=serializer.validated_data.get("stage"),
                ip_address=_client_ip(request),
            )
        except JourneyNotTerminalError:
            return error_response(
                ErrorCode.JOURNEY_NOT_TERMINAL,
                "Only a completed, closed, or deferred journey can be reopened.",
                http_status=status.HTTP_409_CONFLICT,
            )
        except InvalidStageTransitionError:
            return _invalid_transition()
        return success_response(data=JourneyDetailSerializer(updated).data, message="Journey reopened.")


class JourneyHistoryView(JourneyScopedView):
    """GET /api/v1/journeys/<id>/history/ — the journey's chronological history."""

    def get(self, request: Request, journey_id: str) -> Response:
        journey, err = self.resolve(request, journey_id)
        if err:
            return err
        return _paginated(
            request,
            get_history_for_journey(journey),
            AuditEventHistorySerializer,
            "History retrieved.",
        )
