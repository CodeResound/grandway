"""Thin views for the offers app.

Views receive the request, apply the interim access checks (§9, ``access.py``),
validate input, call a service, translate domain exceptions into the standard
error envelope, and shape the response. No business logic lives here.

Access is one rule throughout: **any Admin or Lead Manager, for both read and
write.** See ``docs/SECURITY.md`` §1.
"""

from __future__ import annotations

from typing import Any

from applicant_journeys.selectors import get_journey_by_id
from core.pagination import StandardPagination
from core.responses import error_response, success_response
from institutions.selectors import get_campus_by_id, get_institution_by_id, get_program_by_id
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from offers import services
from offers.access import require_offer_actor
from offers.constants import ErrorCode
from offers.exceptions import (
    AcceptedOfferExistsError,
    ActorNotPermittedError,
    AmountIncompleteError,
    CatalogueReferenceInvalidError,
    ConditionNoteRequiredError,
    DecisionReasonRequiredError,
    DeferIntakeRequiredError,
    OfferNotDecidableError,
    OfferNotIssuableError,
    ProgramReferenceRequiredError,
)
from offers.models import Offer, OfferCondition
from offers.selectors import (
    filter_offers,
    get_condition_by_id,
    get_conditions_for_offer,
    get_history_for_offer,
    get_offer_by_id,
    get_offers,
)
from offers.serializers import (
    ConditionCreateSerializer,
    ConditionSerializer,
    ConditionStatusSerializer,
    ConditionUpdateSerializer,
    DecisionSerializer,
    OfferCreateSerializer,
    OfferDetailSerializer,
    OfferHistorySerializer,
    OfferListSerializer,
    OfferSearchSerializer,
    OfferUpdateSerializer,
)


def _client_ip(request: Request) -> str | None:
    return request.META.get("REMOTE_ADDR")


def _forbidden() -> Response:
    return error_response(
        ErrorCode.ACTOR_FORBIDDEN,
        "Your authority level may not perform this action.",
        http_status=status.HTTP_403_FORBIDDEN,
    )


def _not_found(code: str, message: str) -> Response:
    return error_response(code, message, http_status=status.HTTP_404_NOT_FOUND)


def _bad_request(code: str, message: str, details: dict[str, Any] | None = None) -> Response:
    return error_response(code, message, details=details, http_status=status.HTTP_400_BAD_REQUEST)


def _conflict(code: str, message: str) -> Response:
    return error_response(code, message, http_status=status.HTTP_409_CONFLICT)


def _paginated(request: Request, queryset: Any, serializer_class: Any, message: str) -> Response:
    paginator = StandardPagination()
    page = paginator.paginate_queryset(queryset, request)
    serializer = serializer_class(page if page is not None else queryset, many=True)
    if page is not None:
        return paginator.get_paginated_response(serializer.data)
    return success_response(data=serializer.data, message=message)


def _validated_filters(request: Request) -> dict[str, Any]:
    """Validate the query string, or raise DRF's ``ValidationError``."""
    serializer = OfferSearchSerializer(data=request.query_params)
    serializer.is_valid(raise_exception=True)
    return serializer.validated_data


class OfferScopedView(APIView):
    """Base for every view addressing a single offer by id."""

    permission_classes = [IsAuthenticated]

    def resolve(self, request: Request, offer_id: str) -> tuple[Offer | None, Response | None]:
        try:
            require_offer_actor(request.user)
        except ActorNotPermittedError:
            return None, _forbidden()
        offer = get_offer_by_id(offer_id)
        if offer is None:
            return None, _not_found(ErrorCode.OFFER_NOT_FOUND, "Offer not found.")
        return offer, None


class ConditionScopedView(APIView):
    """Base for every view addressing a single condition by id.

    Authority is checked against the app, and the parent offer comes along with
    the condition — every condition action is audited against its offer.
    """

    permission_classes = [IsAuthenticated]

    def resolve(self, request: Request, condition_id: str) -> tuple[OfferCondition | None, Response | None]:
        try:
            require_offer_actor(request.user)
        except ActorNotPermittedError:
            return None, _forbidden()
        condition = get_condition_by_id(condition_id)
        if condition is None:
            return None, _not_found(ErrorCode.CONDITION_NOT_FOUND, "Offer condition not found.")
        return condition, None


class OfferListCreateView(APIView):
    """GET/POST /api/v1/offers/ — list offers, or record an institution's decision."""

    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        try:
            require_offer_actor(request.user)
        except ActorNotPermittedError:
            return _forbidden()
        queryset = filter_offers(get_offers(), _validated_filters(request))
        return _paginated(request, queryset, OfferListSerializer, "Offers retrieved.")

    def post(self, request: Request) -> Response:
        try:
            require_offer_actor(request.user)
        except ActorNotPermittedError:
            return _forbidden()
        serializer = OfferCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)

        journey = get_journey_by_id(str(data.pop("journey")))
        if journey is None:
            return _bad_request(
                ErrorCode.JOURNEY_NOT_FOUND,
                "Journey not found.",
                details={"journey": ["No journey with that id."]},
            )

        catalogue, err = self._resolve_catalogue(data)
        if err:
            return err

        conditions = [dict(c) for c in data.pop("conditions", [])]
        try:
            offer = services.create_offer(
                actor=request.user,
                journey=journey,
                data=data,
                conditions=conditions,
                ip_address=_client_ip(request),
                **catalogue,
            )
        except ProgramReferenceRequiredError as exc:
            return _bad_request(
                ErrorCode.PROGRAM_REFERENCE_REQUIRED,
                str(exc),
                details={"program": ["Provide a catalogue program, or the institution and program names."]},
            )
        except CatalogueReferenceInvalidError as exc:
            return _bad_request(ErrorCode.CATALOGUE_REFERENCE_INVALID, str(exc))
        except AmountIncompleteError as exc:
            return _bad_request(ErrorCode.AMOUNT_INCOMPLETE, str(exc))

        return success_response(
            data=OfferDetailSerializer(offer).data,
            message="Offer recorded.",
            http_status=status.HTTP_201_CREATED,
        )

    @staticmethod
    def _resolve_catalogue(data: dict[str, Any]) -> tuple[dict[str, Any], Response | None]:
        """Turn the submitted catalogue ids into records, or explain which one is wrong."""
        resolved: dict[str, Any] = {}
        lookups = (
            ("institution", get_institution_by_id),
            ("campus", get_campus_by_id),
            ("program", get_program_by_id),
        )
        for field, lookup in lookups:
            raw = data.pop(field, None)
            if raw is None:
                resolved[field] = None
                continue
            record = lookup(str(raw))
            if record is None:
                return {}, _bad_request(
                    ErrorCode.CATALOGUE_REFERENCE_INVALID,
                    f"No catalogue {field} with that id.",
                    details={field: ["Not found in the catalogue."]},
                )
            resolved[field] = record
        return resolved, None


class OfferDetailView(OfferScopedView):
    """GET/PATCH /api/v1/offers/<id>/ — read or correct one offer."""

    def get(self, request: Request, offer_id: str) -> Response:
        offer, err = self.resolve(request, offer_id)
        if err:
            return err
        return success_response(data=OfferDetailSerializer(offer).data, message="Offer retrieved.")

    #: Fields a PATCH may not carry. Rejected loudly rather than dropped
    #: silently: a client that sent ``program_title`` and got 200 back would
    #: believe it had corrected the record, and the one thing this app
    #: guarantees is that it did not.
    REJECTED_ON_PATCH = services.IMMUTABLE_FIELDS | {"status", "conditions"}

    def patch(self, request: Request, offer_id: str) -> Response:
        offer, err = self.resolve(request, offer_id)
        if err:
            return err

        attempted = sorted(self.REJECTED_ON_PATCH & set(request.data or {}))
        if attempted:
            return _bad_request(
                ErrorCode.REFERENCE_IMMUTABLE,
                "An offer's journey, catalogue reference, snapshot, and status cannot be edited.",
                details={field: ["This field cannot be changed after the offer is recorded."] for field in attempted},
            )

        serializer = OfferUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        try:
            updated = services.update_offer(
                actor=request.user,
                offer=offer,
                fields=dict(serializer.validated_data),
                ip_address=_client_ip(request),
            )
        except AmountIncompleteError as exc:
            return _bad_request(ErrorCode.AMOUNT_INCOMPLETE, str(exc))
        return success_response(data=OfferDetailSerializer(updated).data, message="Offer updated.")


class OfferIssueView(OfferScopedView):
    """POST /api/v1/offers/<id>/issue/ — mark a drafted offer as issued."""

    def post(self, request: Request, offer_id: str) -> Response:
        offer, err = self.resolve(request, offer_id)
        if err:
            return err
        try:
            updated = services.issue_offer(actor=request.user, offer=offer, ip_address=_client_ip(request))
        except OfferNotIssuableError as exc:
            return _conflict(ErrorCode.OFFER_NOT_ISSUABLE, str(exc))
        return success_response(data=OfferDetailSerializer(updated).data, message="Offer issued.")


class OfferDecisionView(OfferScopedView):
    """POST /api/v1/offers/<id>/decision/ — record accept, reject, withdraw, defer, or expire."""

    def post(self, request: Request, offer_id: str) -> Response:
        offer, err = self.resolve(request, offer_id)
        if err:
            return err
        serializer = DecisionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            updated = services.record_decision(
                actor=request.user,
                offer=offer,
                outcome=data["outcome"],
                reason=data.get("reason", ""),
                to_intake=data.get("to_intake", ""),
                ip_address=_client_ip(request),
            )
        except OfferNotDecidableError as exc:
            return _conflict(ErrorCode.OFFER_NOT_DECIDABLE, str(exc))
        except AcceptedOfferExistsError as exc:
            return _conflict(ErrorCode.ACCEPTED_OFFER_EXISTS, str(exc))
        except DecisionReasonRequiredError as exc:
            return _bad_request(
                ErrorCode.DECISION_REASON_REQUIRED,
                str(exc),
                details={"reason": ["This field is required for the selected outcome."]},
            )
        except DeferIntakeRequiredError as exc:
            return _bad_request(
                ErrorCode.DEFER_INTAKE_REQUIRED,
                str(exc),
                details={"to_intake": ["This field is required when deferring."]},
            )
        return success_response(data=OfferDetailSerializer(updated).data, message="Decision recorded.")


class OfferHistoryView(OfferScopedView):
    """GET /api/v1/offers/<id>/history/ — the offer's chronological history."""

    def get(self, request: Request, offer_id: str) -> Response:
        offer, err = self.resolve(request, offer_id)
        if err:
            return err
        return _paginated(request, get_history_for_offer(offer), OfferHistorySerializer, "History retrieved.")


class ConditionListCreateView(OfferScopedView):
    """GET/POST /api/v1/offers/<id>/conditions/ — list or attach offer conditions."""

    def get(self, request: Request, offer_id: str) -> Response:
        offer, err = self.resolve(request, offer_id)
        if err:
            return err
        return _paginated(
            request,
            get_conditions_for_offer(str(offer.id)),
            ConditionSerializer,
            "Conditions retrieved.",
        )

    def post(self, request: Request, offer_id: str) -> Response:
        offer, err = self.resolve(request, offer_id)
        if err:
            return err
        serializer = ConditionCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        condition = services.create_condition(
            actor=request.user,
            offer=offer,
            data=dict(serializer.validated_data),
            ip_address=_client_ip(request),
        )
        return success_response(
            data=ConditionSerializer(condition).data,
            message="Condition added.",
            http_status=status.HTTP_201_CREATED,
        )


class ConditionDetailView(ConditionScopedView):
    """PATCH /api/v1/offers/conditions/<id>/ — correct a condition's details."""

    def patch(self, request: Request, condition_id: str) -> Response:
        condition, err = self.resolve(request, condition_id)
        if err:
            return err
        serializer = ConditionUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        updated = services.update_condition(
            actor=request.user,
            condition=condition,
            fields=dict(serializer.validated_data),
            ip_address=_client_ip(request),
        )
        return success_response(data=ConditionSerializer(updated).data, message="Condition updated.")


class ConditionStatusView(ConditionScopedView):
    """POST /api/v1/offers/conditions/<id>/status/ — resolve, waive, retire, or reopen."""

    def post(self, request: Request, condition_id: str) -> Response:
        condition, err = self.resolve(request, condition_id)
        if err:
            return err
        serializer = ConditionStatusSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            updated = services.change_condition_status(
                actor=request.user,
                condition=condition,
                status=data["status"],
                note=data.get("note", ""),
                ip_address=_client_ip(request),
            )
        except ConditionNoteRequiredError as exc:
            return _bad_request(
                ErrorCode.CONDITION_NOTE_REQUIRED,
                str(exc),
                details={"note": ["This field is required for the selected status."]},
            )
        return success_response(data=ConditionSerializer(updated).data, message="Condition status updated.")
