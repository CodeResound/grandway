"""Thin views for the applicants app.

Views receive the request, apply the interim access checks (§9, ``access.py``),
validate input, call a service, translate domain exceptions into the standard
error envelope, and shape the response. No business logic lives here.
"""

from __future__ import annotations

from typing import Any

from audit.serializers import AuditEventHistorySerializer
from authenticate.selectors import get_active_user_by_id
from core.constants import ErrorCode as CoreErrorCode
from core.pagination import StandardPagination
from core.responses import error_response, success_response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from applicants import services
from applicants.access import require_admin, require_applicant_actor
from applicants.constants import ASSIGNED_TO_ME, ErrorCode
from applicants.exceptions import (
    ActorNotPermittedError,
    ApplicantArchivedError,
    ApplicantNotArchivedError,
    AssigneeInvalidError,
    AssignmentNotPermittedError,
    ContactNumberRequiredError,
    EducationInvalidError,
    LanguageTestInvalidError,
    NoteBodyRequiredError,
    NoteFutureDateError,
    NoteNotPermittedError,
    PassportExpiryInvalidError,
)
from applicants.models import Applicant
from applicants.selectors import (
    filter_applicants,
    get_applicant_by_id,
    get_applicants,
    get_history_for_applicant,
    get_note_category_counts,
    get_note_for_applicant,
    get_notes_for_applicant,
    rank_applicants,
)
from applicants.serializers import (
    ApplicantCreateSerializer,
    ApplicantDetailSerializer,
    ApplicantListFilterSerializer,
    ApplicantListSerializer,
    ApplicantNoteCreateSerializer,
    ApplicantNoteListFilterSerializer,
    ApplicantNoteSerializer,
    ApplicantNoteUpdateSerializer,
    ApplicantUpdateSerializer,
    AssignSerializer,
    RestoreSerializer,
    StatusChangeSerializer,
)

#: Nested collections pulled out of the applicant payload before it reaches the
#: service. Each replaces its set wholesale; the passport is upserted.
_NESTED_KEYS = (
    "contact_numbers",
    "addresses",
    "family_members",
    "emergency_contacts",
    "passport",
    "educations",
    "language_tests",
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
        ErrorCode.APPLICANT_NOT_FOUND,
        "Applicant not found.",
        http_status=status.HTTP_404_NOT_FOUND,
    )


def _archived_conflict(message: str) -> Response:
    return error_response(ErrorCode.APPLICANT_ARCHIVED, message, http_status=status.HTTP_409_CONFLICT)


def _note_not_found() -> Response:
    return error_response(ErrorCode.NOTE_NOT_FOUND, "Note not found.", http_status=status.HTTP_404_NOT_FOUND)


_NOTE_WRITE_ERRORS = (ApplicantArchivedError, NoteNotPermittedError, NoteFutureDateError, NoteBodyRequiredError)


def _note_write_error(exc: Exception) -> Response:
    """Translate the domain errors shared by every note write (``_NOTE_WRITE_ERRORS``)."""
    if isinstance(exc, ApplicantArchivedError):
        return _archived_conflict("This applicant is archived; an Admin must restore them before notes change.")
    if isinstance(exc, NoteNotPermittedError):
        return error_response(
            ErrorCode.NOTE_FORBIDDEN,
            "Only the note's author or an Admin may change it.",
            http_status=status.HTTP_403_FORBIDDEN,
        )
    if isinstance(exc, NoteFutureDateError):
        return error_response(
            ErrorCode.NOTE_FUTURE_DATE,
            "A note cannot be dated in the future.",
            details={"noted_at": ["Must not be later than now."]},
            http_status=status.HTTP_400_BAD_REQUEST,
        )
    if isinstance(exc, NoteBodyRequiredError):
        # Normally refused earlier by the serializer (DRF trims whitespace);
        # reached only if normalization empties a body.
        return error_response(
            CoreErrorCode.VALIDATION_ERROR,
            "A note needs some text.",
            details={"body": ["This field may not be blank."]},
            http_status=status.HTTP_400_BAD_REQUEST,
        )
    raise exc


def _academic_error(exc: EducationInvalidError | LanguageTestInvalidError) -> Response:
    """400 for an education or language-test entry that breaks a rule, every failing path listed."""
    code = ErrorCode.EDUCATION_INVALID if isinstance(exc, EducationInvalidError) else ErrorCode.LANGUAGE_TEST_INVALID
    return error_response(code, str(exc), details={"fields": exc.fields}, http_status=status.HTTP_400_BAD_REQUEST)


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
        if filters.get("assigned_to") == ASSIGNED_TO_ME:
            filters["assigned_to"] = str(request.user.id)
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
                educations=nested.get("educations"),
                language_tests=nested.get("language_tests"),
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
        except (EducationInvalidError, LanguageTestInvalidError) as exc:
            return _academic_error(exc)
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
                educations=nested.get("educations"),
                language_tests=nested.get("language_tests"),
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
        except (EducationInvalidError, LanguageTestInvalidError) as exc:
            return _academic_error(exc)
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
        try:
            updated = services.change_status(
                actor=request.user,
                applicant=applicant,
                status=serializer.validated_data["status"],
                ip_address=_client_ip(request),
            )
        except ApplicantArchivedError:
            return _archived_conflict("This applicant is archived; an Admin restores them with POST /restore/.")
        return success_response(
            data=ApplicantDetailSerializer(updated).data,
            message="Applicant status updated.",
        )


class ApplicantRestoreView(ApplicantScopedView):
    """POST /api/v1/applicants/<id>/restore/ — un-archive to the prior status. Admin only."""

    def post(self, request: Request, applicant_id: str) -> Response:
        applicant, err = self.resolve(request, applicant_id)
        if err:
            return err
        try:
            require_admin(request.user)
        except ActorNotPermittedError:
            return _forbidden()
        serializer = RestoreSerializer(data=request.data or {})
        serializer.is_valid(raise_exception=True)
        try:
            restored = services.restore_applicant(
                actor=request.user,
                applicant=applicant,
                reason=serializer.validated_data.get("reason", ""),
                ip_address=_client_ip(request),
            )
        except ApplicantNotArchivedError:
            return error_response(
                ErrorCode.APPLICANT_NOT_ARCHIVED,
                "Only an archived applicant can be restored.",
                http_status=status.HTTP_409_CONFLICT,
            )
        return success_response(data=ApplicantDetailSerializer(restored).data, message="Applicant restored.")


class ApplicantAssignView(ApplicantScopedView):
    """POST /api/v1/applicants/<id>/assign/ — set or clear who is notified about this file.

    Routing only; access to the applicant is unchanged. The take/release rule for
    Lead Managers lives in ``services.assign_applicant``.
    """

    def post(self, request: Request, applicant_id: str) -> Response:
        applicant, err = self.resolve(request, applicant_id)
        if err:
            return err
        serializer = AssignSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        assignee_id = serializer.validated_data["assigned_to"]
        assignee = get_active_user_by_id(str(assignee_id)) if assignee_id else None
        try:
            if assignee_id and assignee is None:
                raise AssigneeInvalidError("The assignee must be an active Admin or Lead Manager.")
            updated = services.assign_applicant(
                actor=request.user,
                applicant=applicant,
                assignee=assignee,
                ip_address=_client_ip(request),
            )
        except AssigneeInvalidError as exc:
            return error_response(
                ErrorCode.ASSIGNEE_INVALID,
                str(exc),
                details={"assigned_to": [str(exc)]},
                http_status=status.HTTP_400_BAD_REQUEST,
            )
        except AssignmentNotPermittedError as exc:
            return error_response(ErrorCode.ASSIGNMENT_FORBIDDEN, str(exc), http_status=status.HTTP_403_FORBIDDEN)
        except ApplicantArchivedError:
            return _archived_conflict("This applicant is archived; an Admin restores them with POST /restore/.")
        return success_response(data=ApplicantDetailSerializer(updated).data, message="Applicant assignment updated.")


class ApplicantNoteListCreateView(ApplicantScopedView):
    """GET/POST /api/v1/applicants/<id>/notes/ — read the notes feed, or write a note."""

    def get(self, request: Request, applicant_id: str) -> Response:
        applicant, err = self.resolve(request, applicant_id)
        if err:
            return err
        filters = ApplicantNoteListFilterSerializer(data=request.query_params)
        filters.is_valid(raise_exception=True)
        queryset = get_notes_for_applicant(
            applicant,
            category=filters.validated_data.get("category"),
            ordering=filters.validated_data.get("ordering"),
        )
        response = _paginated(request, queryset, ApplicantNoteSerializer, "Notes retrieved.")
        # Per-category totals so both tabs can show a badge from one request.
        response.data.setdefault("meta", {})["counts"] = get_note_category_counts(applicant)
        return response

    def post(self, request: Request, applicant_id: str) -> Response:
        applicant, err = self.resolve(request, applicant_id)
        if err:
            return err
        serializer = ApplicantNoteCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            note = services.add_note(
                actor=request.user,
                applicant=applicant,
                body=data["body"],
                category=data["category"],
                noted_at=data.get("noted_at"),
                ip_address=_client_ip(request),
            )
        except _NOTE_WRITE_ERRORS as exc:
            return _note_write_error(exc)
        return success_response(
            data=ApplicantNoteSerializer(note).data,
            message="Note added.",
            http_status=status.HTTP_201_CREATED,
        )


class ApplicantNoteDetailView(ApplicantScopedView):
    """PATCH/DELETE /api/v1/applicants/<id>/notes/<note_id>/ — correct or remove a note.

    The author or an Admin only. Delete is soft: the note leaves the feed, the
    row and its audit trail stay.
    """

    def _resolve_note(self, request: Request, applicant_id: str, note_id: str) -> tuple[Any, Any, Response | None]:
        applicant, err = self.resolve(request, applicant_id)
        if err:
            return None, None, err
        note = get_note_for_applicant(applicant, note_id)
        if note is None:
            return None, None, _note_not_found()
        return applicant, note, None

    def patch(self, request: Request, applicant_id: str, note_id: str) -> Response:
        applicant, note, err = self._resolve_note(request, applicant_id, note_id)
        if err:
            return err
        serializer = ApplicantNoteUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        try:
            updated = services.update_note(
                actor=request.user,
                applicant=applicant,
                note=note,
                fields=dict(serializer.validated_data),
                ip_address=_client_ip(request),
            )
        except _NOTE_WRITE_ERRORS as exc:
            return _note_write_error(exc)
        return success_response(data=ApplicantNoteSerializer(updated).data, message="Note updated.")

    def delete(self, request: Request, applicant_id: str, note_id: str) -> Response:
        applicant, note, err = self._resolve_note(request, applicant_id, note_id)
        if err:
            return err
        try:
            services.delete_note(actor=request.user, applicant=applicant, note=note, ip_address=_client_ip(request))
        except _NOTE_WRITE_ERRORS as exc:
            return _note_write_error(exc)
        return success_response(data=None, message="Note deleted.")


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
