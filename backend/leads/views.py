"""Thin views for the leads app.

Views receive the request, apply the interim access checks (§9, ``access.py``),
validate input, call a service, translate domain exceptions into the standard
error envelope, and shape the response. No business logic lives here.

A lead outside the caller's scope is reported as 404, never 403 — see
``docs/SECURITY.md`` §1.
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

from leads import services
from leads.access import require_admin, require_lead_actor
from leads.constants import ErrorCode
from leads.exceptions import (
    ActorNotPermittedError,
    ContactNumberRequiredError,
    ConversionNotReadyError,
    InvalidStageTransitionError,
    LeadAlreadyConvertedError,
    LeadNotLostError,
    LossDetailRequiredError,
    LossReasonRequiredError,
    ReferenceCodeTakenError,
    ReferenceInactiveError,
    SourceDetailRequiredError,
    StageNotEditableError,
)
from leads.models import Lead
from leads.selectors import (
    filter_leads,
    get_history_for_lead,
    get_lead_for_actor,
    get_lead_source_by_id,
    get_lead_sources,
    get_leads_for_actor,
    get_loss_reason_by_id,
    get_loss_reasons,
    get_notes_for_lead,
    rank_leads,
)
from leads.serializers import (
    FollowUpSerializer,
    LeadCreateSerializer,
    LeadDetailSerializer,
    LeadListFilterSerializer,
    LeadListSerializer,
    LeadNoteCreateSerializer,
    LeadNoteSerializer,
    LeadSourceSerializer,
    LeadUpdateSerializer,
    LossReasonSerializer,
    MarkLostSerializer,
    ReferenceEntryUpdateSerializer,
    ReferenceEntryWriteSerializer,
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


def _lead_not_found() -> Response:
    return error_response(
        ErrorCode.LEAD_NOT_FOUND,
        "Lead not found.",
        http_status=status.HTTP_404_NOT_FOUND,
    )


def _paginated(request: Request, queryset: Any, serializer_class: Any, message: str) -> Response:
    paginator = StandardPagination()
    page = paginator.paginate_queryset(queryset, request)
    serializer = serializer_class(page if page is not None else queryset, many=True)
    if page is not None:
        return paginator.get_paginated_response(serializer.data)
    return success_response(data=serializer.data, message=message)


class LeadScopedView(APIView):
    """Base for every view addressing a single lead by id.

    Resolves the lead through the owner-scoped selector so "not found" and "not
    yours" are indistinguishable to the caller.
    """

    permission_classes = [IsAuthenticated]

    def resolve(self, request: Request, lead_id: str) -> tuple[Lead | None, Response | None]:
        try:
            require_lead_actor(request.user)
        except ActorNotPermittedError:
            return None, _forbidden()
        lead = get_lead_for_actor(request.user, lead_id)
        if lead is None:
            return None, _lead_not_found()
        return lead, None


# ---------------------------------------------------------------------------
# Reference configuration
# ---------------------------------------------------------------------------


class LeadSourceListCreateView(APIView):
    """GET/POST /api/v1/leads/sources/ — list active sources, or add one (Admin)."""

    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        try:
            require_lead_actor(request.user)
        except ActorNotPermittedError:
            return _forbidden()
        include_inactive = request.query_params.get("include_inactive") == "true"
        sources = get_lead_sources(include_inactive=include_inactive)
        return success_response(
            data=LeadSourceSerializer(sources, many=True).data,
            message="Lead sources retrieved.",
        )

    def post(self, request: Request) -> Response:
        try:
            require_admin(request.user)
        except ActorNotPermittedError:
            return _forbidden()
        serializer = ReferenceEntryWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            source = services.create_lead_source(
                actor=request.user,
                data=serializer.validated_data,
                ip_address=_client_ip(request),
            )
        except ReferenceCodeTakenError:
            return error_response(
                ErrorCode.SOURCE_CODE_TAKEN,
                "A lead source with that code already exists.",
                http_status=status.HTTP_409_CONFLICT,
            )
        return success_response(
            data=LeadSourceSerializer(source).data,
            message="Lead source created.",
            http_status=status.HTTP_201_CREATED,
        )


class LeadSourceDetailView(APIView):
    """PATCH /api/v1/leads/sources/<id>/ — edit or deactivate a source (Admin)."""

    permission_classes = [IsAuthenticated]

    def patch(self, request: Request, source_id: str) -> Response:
        try:
            require_admin(request.user)
        except ActorNotPermittedError:
            return _forbidden()
        source = get_lead_source_by_id(source_id)
        if source is None:
            return error_response(
                ErrorCode.SOURCE_NOT_FOUND,
                "Lead source not found.",
                http_status=status.HTTP_404_NOT_FOUND,
            )
        serializer = ReferenceEntryUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        updated = services.update_lead_source(
            actor=request.user,
            source=source,
            fields=serializer.validated_data,
            ip_address=_client_ip(request),
        )
        return success_response(data=LeadSourceSerializer(updated).data, message="Lead source updated.")


class LossReasonListCreateView(APIView):
    """GET/POST /api/v1/leads/loss-reasons/ — list active reasons, or add one (Admin)."""

    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        try:
            require_lead_actor(request.user)
        except ActorNotPermittedError:
            return _forbidden()
        include_inactive = request.query_params.get("include_inactive") == "true"
        reasons = get_loss_reasons(include_inactive=include_inactive)
        return success_response(
            data=LossReasonSerializer(reasons, many=True).data,
            message="Loss reasons retrieved.",
        )

    def post(self, request: Request) -> Response:
        try:
            require_admin(request.user)
        except ActorNotPermittedError:
            return _forbidden()
        serializer = ReferenceEntryWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            reason = services.create_loss_reason(
                actor=request.user,
                data=serializer.validated_data,
                ip_address=_client_ip(request),
            )
        except ReferenceCodeTakenError:
            return error_response(
                ErrorCode.LOSS_REASON_CODE_TAKEN,
                "A loss reason with that code already exists.",
                http_status=status.HTTP_409_CONFLICT,
            )
        return success_response(
            data=LossReasonSerializer(reason).data,
            message="Loss reason created.",
            http_status=status.HTTP_201_CREATED,
        )


class LossReasonDetailView(APIView):
    """PATCH /api/v1/leads/loss-reasons/<id>/ — edit or deactivate a reason (Admin)."""

    permission_classes = [IsAuthenticated]

    def patch(self, request: Request, reason_id: str) -> Response:
        try:
            require_admin(request.user)
        except ActorNotPermittedError:
            return _forbidden()
        reason = get_loss_reason_by_id(reason_id)
        if reason is None:
            return error_response(
                ErrorCode.LOSS_REASON_NOT_FOUND,
                "Loss reason not found.",
                http_status=status.HTTP_404_NOT_FOUND,
            )
        serializer = ReferenceEntryUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        updated = services.update_loss_reason(
            actor=request.user,
            reason=reason,
            fields=serializer.validated_data,
            ip_address=_client_ip(request),
        )
        return success_response(data=LossReasonSerializer(updated).data, message="Loss reason updated.")


# ---------------------------------------------------------------------------
# Leads
# ---------------------------------------------------------------------------


class LeadListCreateView(APIView):
    """GET/POST /api/v1/leads/ — list leads in scope, or record a new enquiry."""

    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        try:
            require_lead_actor(request.user)
        except ActorNotPermittedError:
            return _forbidden()
        filter_serializer = LeadListFilterSerializer(data=request.query_params)
        filter_serializer.is_valid(raise_exception=True)
        filters = dict(filter_serializer.validated_data)
        search = filters.get("search")
        queryset = filter_leads(get_leads_for_actor(request.user), filters)
        # Relevance ordering applies only when there is a query to be relevant
        # to; an unsearched list keeps the model's newest-first ordering.
        if search:
            queryset = rank_leads(queryset, search)
        return _paginated(request, queryset, LeadListSerializer, "Leads retrieved.")

    def post(self, request: Request) -> Response:
        try:
            require_lead_actor(request.user)
        except ActorNotPermittedError:
            return _forbidden()
        serializer = LeadCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        contact_numbers = data.pop("contact_numbers")
        study_interest = data.pop("study_interest", None)

        try:
            lead = services.create_lead(
                actor=request.user,
                data=data,
                contact_numbers=contact_numbers,
                study_interest=study_interest,
                ip_address=_client_ip(request),
            )
        except ReferenceInactiveError:
            return error_response(
                ErrorCode.SOURCE_INACTIVE,
                "That lead source is no longer available.",
                http_status=status.HTTP_400_BAD_REQUEST,
            )
        except SourceDetailRequiredError:
            return error_response(
                ErrorCode.SOURCE_DETAIL_REQUIRED,
                "This lead source requires a short description.",
                details={"source_detail": ["This field is required for the selected source."]},
                http_status=status.HTTP_400_BAD_REQUEST,
            )
        except ContactNumberRequiredError:
            return error_response(
                ErrorCode.CONTACT_REQUIRED,
                "A lead needs at least one contact number.",
                http_status=status.HTTP_400_BAD_REQUEST,
            )
        return success_response(
            data=LeadDetailSerializer(lead).data,
            message="Lead created.",
            http_status=status.HTTP_201_CREATED,
        )


class LeadDetailView(LeadScopedView):
    """GET/PATCH /api/v1/leads/<id>/ — read or correct a lead."""

    def get(self, request: Request, lead_id: str) -> Response:
        lead, err = self.resolve(request, lead_id)
        if err:
            return err
        return success_response(data=LeadDetailSerializer(lead).data, message="Lead retrieved.")

    def patch(self, request: Request, lead_id: str) -> Response:
        lead, err = self.resolve(request, lead_id)
        if err:
            return err
        serializer = LeadUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        fields = dict(serializer.validated_data)
        contact_numbers = fields.pop("contact_numbers", None)
        study_interest = fields.pop("study_interest", None)

        try:
            updated = services.update_lead(
                actor=request.user,
                lead=lead,
                fields=fields,
                contact_numbers=contact_numbers,
                study_interest=study_interest,
                ip_address=_client_ip(request),
            )
        except ReferenceInactiveError:
            return error_response(
                ErrorCode.SOURCE_INACTIVE,
                "That lead source is no longer available.",
                http_status=status.HTTP_400_BAD_REQUEST,
            )
        except SourceDetailRequiredError:
            return error_response(
                ErrorCode.SOURCE_DETAIL_REQUIRED,
                "This lead source requires a short description.",
                details={"source_detail": ["This field is required for the selected source."]},
                http_status=status.HTTP_400_BAD_REQUEST,
            )
        except ContactNumberRequiredError:
            return error_response(
                ErrorCode.CONTACT_REQUIRED,
                "A lead needs at least one contact number.",
                http_status=status.HTTP_400_BAD_REQUEST,
            )
        return success_response(data=LeadDetailSerializer(updated).data, message="Lead updated.")


class LeadStageView(LeadScopedView):
    """POST /api/v1/leads/<id>/stage/ — move a lead between active stages."""

    def post(self, request: Request, lead_id: str) -> Response:
        lead, err = self.resolve(request, lead_id)
        if err:
            return err
        serializer = StageChangeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            updated = services.change_stage(
                actor=request.user,
                lead=lead,
                stage=serializer.validated_data["stage"],
                ip_address=_client_ip(request),
            )
        except StageNotEditableError:
            return error_response(
                ErrorCode.STAGE_NOT_EDITABLE,
                "This lead is lost or converted; reopen it before changing its stage.",
                http_status=status.HTTP_409_CONFLICT,
            )
        except InvalidStageTransitionError:
            return error_response(
                ErrorCode.STAGE_INVALID_TRANSITION,
                "This stage cannot be selected directly; use the mark-lost or convert action.",
                http_status=status.HTTP_400_BAD_REQUEST,
            )
        return success_response(data=LeadDetailSerializer(updated).data, message="Stage updated.")


class LeadFollowUpView(LeadScopedView):
    """POST /api/v1/leads/<id>/follow-up/ — record a manual follow-up."""

    def post(self, request: Request, lead_id: str) -> Response:
        lead, err = self.resolve(request, lead_id)
        if err:
            return err
        serializer = FollowUpSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            updated = services.record_followup(
                actor=request.user,
                lead=lead,
                note=data.get("note", ""),
                stage=data.get("stage"),
                followed_up_at=data.get("followed_up_at"),
                ip_address=_client_ip(request),
            )
        except StageNotEditableError:
            return error_response(
                ErrorCode.STAGE_NOT_EDITABLE,
                "This lead is lost or converted; reopen it before recording a follow-up.",
                http_status=status.HTTP_409_CONFLICT,
            )
        except InvalidStageTransitionError:
            return error_response(
                ErrorCode.STAGE_INVALID_TRANSITION,
                "This stage cannot be selected directly; use the mark-lost or convert action.",
                http_status=status.HTTP_400_BAD_REQUEST,
            )
        return success_response(data=LeadDetailSerializer(updated).data, message="Follow-up recorded.")


class LeadMarkLostView(LeadScopedView):
    """POST /api/v1/leads/<id>/lost/ — close a lead, with a mandatory reason."""

    def post(self, request: Request, lead_id: str) -> Response:
        lead, err = self.resolve(request, lead_id)
        if err:
            return err
        serializer = MarkLostSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            updated = services.mark_lost(
                actor=request.user,
                lead=lead,
                loss_reason=data["loss_reason"],
                detail=data.get("detail", ""),
                ip_address=_client_ip(request),
            )
        except StageNotEditableError:
            return error_response(
                ErrorCode.STAGE_NOT_EDITABLE,
                "This lead is already lost or converted.",
                http_status=status.HTTP_409_CONFLICT,
            )
        except LossReasonRequiredError:
            return error_response(
                ErrorCode.LOSS_REASON_REQUIRED,
                "A loss reason is required to close a lead.",
                details={"loss_reason": ["This field is required."]},
                http_status=status.HTTP_400_BAD_REQUEST,
            )
        except ReferenceInactiveError:
            return error_response(
                ErrorCode.LOSS_REASON_INACTIVE,
                "That loss reason is no longer available.",
                http_status=status.HTTP_400_BAD_REQUEST,
            )
        except LossDetailRequiredError:
            return error_response(
                ErrorCode.LOSS_DETAIL_REQUIRED,
                "This loss reason requires an explanation.",
                details={"detail": ["This field is required for the selected reason."]},
                http_status=status.HTTP_400_BAD_REQUEST,
            )
        return success_response(data=LeadDetailSerializer(updated).data, message="Lead marked lost.")


class LeadReopenView(LeadScopedView):
    """POST /api/v1/leads/<id>/reopen/ — return a lost or converted lead to active work.

    Reopening a converted lead never undoes the conversion or its applicant link.
    """

    def post(self, request: Request, lead_id: str) -> Response:
        lead, err = self.resolve(request, lead_id)
        if err:
            return err
        serializer = ReopenSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            updated = services.reopen_lead(
                actor=request.user,
                lead=lead,
                stage=serializer.validated_data.get("stage"),
                ip_address=_client_ip(request),
            )
        except LeadNotLostError:
            return error_response(
                ErrorCode.LEAD_NOT_LOST,
                "Only a lost or converted lead can be reopened.",
                http_status=status.HTTP_409_CONFLICT,
            )
        except InvalidStageTransitionError:
            return error_response(
                ErrorCode.STAGE_INVALID_TRANSITION,
                "A lead must be reopened into an active stage.",
                http_status=status.HTTP_400_BAD_REQUEST,
            )
        return success_response(data=LeadDetailSerializer(updated).data, message="Lead reopened.")


class LeadNoteListCreateView(LeadScopedView):
    """GET/POST /api/v1/leads/<id>/notes/ — read or append notes. Notes are never edited."""

    def get(self, request: Request, lead_id: str) -> Response:
        lead, err = self.resolve(request, lead_id)
        if err:
            return err
        return _paginated(request, get_notes_for_lead(lead), LeadNoteSerializer, "Notes retrieved.")

    def post(self, request: Request, lead_id: str) -> Response:
        lead, err = self.resolve(request, lead_id)
        if err:
            return err
        serializer = LeadNoteCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        note = services.add_note(
            actor=request.user,
            lead=lead,
            body=serializer.validated_data["body"],
            ip_address=_client_ip(request),
        )
        return success_response(
            data=LeadNoteSerializer(note).data,
            message="Note added.",
            http_status=status.HTTP_201_CREATED,
        )


class LeadConvertView(LeadScopedView):
    """POST /api/v1/leads/<id>/convert/ — turn a lead into an applicant. Admin only.

    The one point where the lead cycle meets the applicant cycle. Creates an
    applicant plus an initial journey, links both to the lead permanently, and
    moves the lead to its terminal ``converted`` stage.
    """

    def post(self, request: Request, lead_id: str) -> Response:
        lead, err = self.resolve(request, lead_id)
        if err:
            return err
        try:
            require_admin(request.user)
        except ActorNotPermittedError:
            return _forbidden()

        try:
            converted = services.convert_lead(
                actor=request.user,
                lead=lead,
                ip_address=_client_ip(request),
            )
        except LeadAlreadyConvertedError:
            return error_response(
                ErrorCode.LEAD_ALREADY_CONVERTED,
                "This lead has already been converted into an applicant.",
                http_status=status.HTTP_409_CONFLICT,
            )
        except ConversionNotReadyError:
            return error_response(
                ErrorCode.CONVERSION_NOT_READY,
                "A lost or converted lead must be reopened before it can be converted.",
                http_status=status.HTTP_409_CONFLICT,
            )
        return success_response(
            data={
                "lead": LeadDetailSerializer(converted).data,
                "applicant_id": str(converted.converted_applicant_id),
                "journey_id": str(converted.converted_journey_id),
            },
            message="Lead converted to applicant.",
            http_status=status.HTTP_201_CREATED,
        )


class LeadHistoryView(LeadScopedView):
    """GET /api/v1/leads/<id>/history/ — the lead's chronological action history.

    Projected from the central audit log; entries are never rewritten or removed.
    """

    def get(self, request: Request, lead_id: str) -> Response:
        lead, err = self.resolve(request, lead_id)
        if err:
            return err
        return _paginated(request, get_history_for_lead(lead), AuditEventHistorySerializer, "History retrieved.")
