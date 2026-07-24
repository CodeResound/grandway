"""Thin views for the checklists app.

Views receive the request, apply the interim access check (§9, ``access.py``),
validate input, call a service, translate domain exceptions into the standard
error envelope, and shape the response. No business logic lives here.

**Two authority levels, expressed as two functions.** Template authoring is
Admin-only; everything else is Admin or Lead Manager. ``uploaded_files`` draws
the same split with two base classes, which does not work here: ``GET
/templates/`` and ``POST /templates/`` are the same view and different
authorities, so a base class would have had to lie about one of them.

**Foreign ids are resolved here, not in services.** A journey, a country, an
assignee, and an evidence file all arrive as UUIDs; the view turns each into a
record (or a 400 naming the field) so that services receive real objects and can
be called from the management command and the signal without a request.
"""

from __future__ import annotations

import logging
from typing import Any

from applicant_journeys.selectors import get_journey_by_id
from authenticate.selectors import get_active_user_by_id
from core.pagination import StandardPagination
from core.responses import error_response, success_response
from institutions.selectors import get_country_by_id
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from checklists import services
from checklists.access import require_admin, require_checklist_actor
from checklists.constants import ChecklistOrigin, ErrorCode
from checklists.exceptions import (
    ActorNotPermittedError,
    ArchiveReasonRequiredError,
    ChecklistArchivedError,
    ChecklistNotArchivedError,
    DefaultRequiresCountryError,
    DefaultTemplateExistsError,
    EvidenceNotAllowedError,
    InvalidTransitionError,
    RequiredItemsPendingError,
    StatusNoteRequiredError,
    TemplateAlreadyAppliedError,
    TemplateHasNoItemsError,
    TemplateNotActiveError,
)
from checklists.models import Checklist, ChecklistTemplate, ChecklistTemplateItem
from checklists.selectors import (
    filter_checklists,
    filter_templates,
    get_checklist_by_id,
    get_checklists,
    get_item_by_id,
    get_journeys_missing_checklist,
    get_template_by_id,
    get_templates,
)
from checklists.serializers import (
    ArchiveSerializer,
    ChecklistCreateSerializer,
    ChecklistDetailSerializer,
    ChecklistItemCreateSerializer,
    ChecklistItemSerializer,
    ChecklistItemUpdateSerializer,
    ChecklistListSerializer,
    ChecklistSearchSerializer,
    ChecklistUpdateSerializer,
    ItemStatusSerializer,
    JourneyMissingChecklistSerializer,
    ReopenSerializer,
    TemplateCreateSerializer,
    TemplateItemCreateSerializer,
    TemplateItemSerializer,
    TemplateItemUpdateSerializer,
    TemplateSearchSerializer,
    TemplateSerializer,
    TemplateUpdateSerializer,
)

logger = logging.getLogger(__name__)


def _client_ip(request: Request) -> str | None:
    return request.META.get("REMOTE_ADDR")


def _forbidden(message: str) -> Response:
    return error_response(ErrorCode.ACTOR_FORBIDDEN, message, http_status=status.HTTP_403_FORBIDDEN)


def _not_found(code: str, message: str) -> Response:
    return error_response(code, message, http_status=status.HTTP_404_NOT_FOUND)


def _bad_request(code: str, message: str, details: dict[str, Any] | None = None) -> Response:
    return error_response(code, message, details=details, http_status=status.HTTP_400_BAD_REQUEST)


def _conflict(code: str, message: str, details: dict[str, Any] | None = None) -> Response:
    return error_response(code, message, details=details, http_status=status.HTTP_409_CONFLICT)


def _search_params(serializer_class: Any, request: Request) -> dict[str, Any]:
    """Validate query parameters and return only the ones actually supplied.

    The final intersection is not defensive tidying. DRF treats a query string
    as HTML input, and a ``BooleanField`` reading HTML input resolves a *missing*
    key to ``False`` rather than skipping it. Without this, every request would
    arrive carrying ``is_default=False`` and ``overdue=False``, and a plain
    ``GET /templates/`` would silently exclude exactly the default templates the
    caller was looking for.
    """
    serializer = serializer_class(data=request.query_params)
    serializer.is_valid(raise_exception=True)
    return {key: value for key, value in serializer.validated_data.items() if key in request.query_params}


def _paginated(request: Request, queryset: Any, serializer_class: Any, message: str) -> Response:
    paginator = StandardPagination()
    page = paginator.paginate_queryset(queryset, request)
    serializer = serializer_class(page if page is not None else queryset, many=True)
    if page is not None:
        return paginator.get_paginated_response(serializer.data)
    return success_response(data=serializer.data, message=message)


def _resolve_country(data: dict[str, Any]) -> Response | None:
    """Swap a ``country`` id for the catalogue row. 400 when it names nothing."""
    if "country" not in data:
        return None
    country_id = data["country"]
    if country_id is None:
        return None
    country = get_country_by_id(str(country_id))
    if country is None:
        return _bad_request(
            ErrorCode.COUNTRY_NOT_FOUND,
            "Country not found in the catalogue.",
            details={"country": ["No country with that id."]},
        )
    data["country"] = country
    return None


def _resolve_assignee(data: dict[str, Any]) -> Response | None:
    """Swap an ``assigned_to`` id for the user record. 400 when it names nobody."""
    if "assigned_to" not in data:
        return None
    user_id = data["assigned_to"]
    if user_id is None:
        return None
    user = get_active_user_by_id(str(user_id))
    if user is None:
        return _bad_request(
            ErrorCode.ACTOR_FORBIDDEN,
            "No active user with that id.",
            details={"assigned_to": ["No active user with that id."]},
        )
    data["assigned_to"] = user
    return None


# ---------------------------------------------------------------------------
# The access split
# ---------------------------------------------------------------------------
#
# Two functions rather than two base classes, because the split does not fall on
# class boundaries: ``GET /templates/`` and ``POST /templates/`` are the same
# view and different authorities. A base class would have had to lie about one
# of them.


def _authorize_actor(request: Request) -> Response | None:
    """Admin or Lead Manager. Every read, and all checklist and item work."""
    try:
        require_checklist_actor(request.user)
    except ActorNotPermittedError as exc:
        return _forbidden(str(exc))
    return None


def _authorize_admin(request: Request) -> Response | None:
    """Admin only. Template authoring.

    Always called *after* ``_authorize_actor``, so a Superadmin is told they may
    not access checklists rather than that Admin authority is required — the
    latter would imply they are one step away from permission they will never
    have.
    """
    err = _authorize_actor(request)
    if err:
        return err
    try:
        require_admin(request.user)
    except ActorNotPermittedError as exc:
        return _forbidden(str(exc))
    return None


class ChecklistActorView(APIView):
    """Base for every view in this app. Carries the shared authority check."""

    permission_classes = [IsAuthenticated]

    def authorize(self, request: Request) -> Response | None:
        return _authorize_actor(request)


# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------


class TemplateListCreateView(ChecklistActorView):
    """GET/POST /api/v1/checklists/templates/ — the country requirement lists."""

    def get(self, request: Request) -> Response:
        err = self.authorize(request)
        if err:
            return err
        queryset = filter_templates(get_templates(), _search_params(TemplateSearchSerializer, request))
        return _paginated(request, queryset, TemplateSerializer, "Checklist templates retrieved.")

    def post(self, request: Request) -> Response:
        err = _authorize_admin(request)
        if err:
            return err

        serializer = TemplateCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)

        country_err = _resolve_country(data)
        if country_err:
            return country_err

        try:
            template = services.create_template(
                actor=request.user,
                data=data,
                ip_address=_client_ip(request),
            )
        except DefaultTemplateExistsError as exc:
            return _conflict(
                ErrorCode.DEFAULT_TEMPLATE_EXISTS,
                str(exc),
                details={"is_default": [str(exc)], "existing_template_id": str(exc.existing.id)},
            )
        except DefaultRequiresCountryError as exc:
            return _bad_request(ErrorCode.DEFAULT_REQUIRES_COUNTRY, str(exc), details={"country": [str(exc)]})

        return success_response(
            data=TemplateSerializer(template).data,
            message="Checklist template created.",
            http_status=status.HTTP_201_CREATED,
        )


class TemplateScopedView(ChecklistActorView):
    """Base for every route addressing one template by id."""

    def resolve(self, request: Request, template_id: str) -> tuple[ChecklistTemplate | None, Response | None]:
        err = self.authorize(request)
        if err:
            return None, err
        template = get_template_by_id(template_id)
        if template is None:
            return None, _not_found(ErrorCode.TEMPLATE_NOT_FOUND, "Checklist template not found.")
        return template, None


class TemplateDetailView(TemplateScopedView):
    """GET/PATCH /api/v1/checklists/templates/<id>/."""

    def get(self, request: Request, template_id: str) -> Response:
        template, err = self.resolve(request, template_id)
        if err:
            return err
        return success_response(data=TemplateSerializer(template).data, message="Checklist template retrieved.")

    def patch(self, request: Request, template_id: str) -> Response:
        template, err = self.resolve(request, template_id)
        if err:
            return err
        admin_err = _authorize_admin(request)
        if admin_err:
            return admin_err

        serializer = TemplateUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        fields = dict(serializer.validated_data)

        country_err = _resolve_country(fields)
        if country_err:
            return country_err

        try:
            updated = services.update_template(
                actor=request.user,
                template=template,
                fields=fields,
                ip_address=_client_ip(request),
            )
        except DefaultTemplateExistsError as exc:
            return _conflict(
                ErrorCode.DEFAULT_TEMPLATE_EXISTS,
                str(exc),
                details={"is_default": [str(exc)], "existing_template_id": str(exc.existing.id)},
            )
        except DefaultRequiresCountryError as exc:
            return _bad_request(ErrorCode.DEFAULT_REQUIRES_COUNTRY, str(exc), details={"country": [str(exc)]})

        return success_response(data=TemplateSerializer(updated).data, message="Checklist template updated.")


class TemplateItemCreateView(TemplateScopedView):
    """POST /api/v1/checklists/templates/<id>/items/ — add a requirement."""

    def post(self, request: Request, template_id: str) -> Response:
        template, err = self.resolve(request, template_id)
        if err:
            return err
        admin_err = _authorize_admin(request)
        if admin_err:
            return admin_err

        serializer = TemplateItemCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        item = services.add_template_item(
            actor=request.user,
            template=template,
            data=dict(serializer.validated_data),
            ip_address=_client_ip(request),
        )
        return success_response(
            data=TemplateItemSerializer(item).data,
            message="Requirement added to template.",
            http_status=status.HTTP_201_CREATED,
        )


class TemplateItemDetailView(TemplateScopedView):
    """PATCH /api/v1/checklists/templates/<id>/items/<item_id>/.

    Retirement is ``is_active: false`` on this route — there is no delete, so a
    live checklist item can always resolve the definition it came from.
    """

    def patch(self, request: Request, template_id: str, item_id: str) -> Response:
        template, err = self.resolve(request, template_id)
        if err:
            return err
        admin_err = _authorize_admin(request)
        if admin_err:
            return admin_err

        item = ChecklistTemplateItem.objects.filter(pk=item_id, template=template).first()
        if item is None:
            return _not_found(ErrorCode.TEMPLATE_ITEM_NOT_FOUND, "Template requirement not found.")

        serializer = TemplateItemUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        updated = services.update_template_item(
            actor=request.user,
            item=item,
            fields=dict(serializer.validated_data),
            ip_address=_client_ip(request),
        )
        return success_response(data=TemplateItemSerializer(updated).data, message="Requirement updated.")


# ---------------------------------------------------------------------------
# Checklists
# ---------------------------------------------------------------------------


class ChecklistListCreateView(ChecklistActorView):
    """GET/POST /api/v1/checklists/ — the applicant-facing lists.

    ``?journey_missing_checklist=true`` on the GET switches this to the safety
    net: journeys that name a country but hold no checklist, because nobody has
    authored that country's requirements yet. It lives on this route rather than
    its own because it answers a question about checklists — the ones that
    should exist and do not.
    """

    def get(self, request: Request) -> Response:
        err = self.authorize(request)
        if err:
            return err

        if request.query_params.get("journey_missing_checklist") in ("true", "True", "1"):
            return _paginated(
                request,
                get_journeys_missing_checklist(),
                JourneyMissingChecklistSerializer,
                "Journeys awaiting a checklist retrieved.",
            )

        queryset = filter_checklists(get_checklists(), _search_params(ChecklistSearchSerializer, request))
        return _paginated(request, queryset, ChecklistListSerializer, "Checklists retrieved.")

    def post(self, request: Request) -> Response:
        err = self.authorize(request)
        if err:
            return err

        serializer = ChecklistCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)

        journey = get_journey_by_id(str(data.pop("journey")))
        if journey is None:
            return _bad_request(
                ErrorCode.JOURNEY_NOT_FOUND,
                "Journey not found.",
                details={"journey": ["No journey with that id."]},
            )

        template_id = data.pop("template", None)
        if template_id:
            return self._apply_template(request, journey, str(template_id))

        assignee_err = _resolve_assignee(data)
        if assignee_err:
            return assignee_err

        checklist = services.create_blank_checklist(
            actor=request.user,
            journey=journey,
            data=data,
            ip_address=_client_ip(request),
        )
        return self._created(checklist)

    def _apply_template(self, request: Request, journey: Any, template_id: str) -> Response:
        """Apply a named template by hand — the override beside the automation."""
        template = get_template_by_id(template_id)
        if template is None:
            return _bad_request(
                ErrorCode.TEMPLATE_NOT_FOUND,
                "Checklist template not found.",
                details={"template": ["No template with that id."]},
            )
        try:
            checklist = services.instantiate_checklist(
                journey=journey,
                template=template,
                origin=ChecklistOrigin.MANUAL,
                actor=request.user,
                ip_address=_client_ip(request),
            )
        except TemplateNotActiveError as exc:
            return _bad_request(ErrorCode.TEMPLATE_NOT_ACTIVE, str(exc), details={"template": [str(exc)]})
        except TemplateHasNoItemsError as exc:
            return _bad_request(ErrorCode.TEMPLATE_HAS_NO_ITEMS, str(exc), details={"template": [str(exc)]})
        except TemplateAlreadyAppliedError as exc:
            return _conflict(ErrorCode.TEMPLATE_ALREADY_APPLIED, str(exc))
        return self._created(checklist)

    @staticmethod
    def _created(checklist: Checklist) -> Response:
        """Re-read through the selector so the response carries progress counts."""
        return success_response(
            data=ChecklistDetailSerializer(get_checklist_by_id(str(checklist.id))).data,
            message="Checklist created.",
            http_status=status.HTTP_201_CREATED,
        )


class ChecklistScopedView(ChecklistActorView):
    """Base for every route addressing one checklist by id."""

    def resolve(self, request: Request, checklist_id: str) -> tuple[Checklist | None, Response | None]:
        err = self.authorize(request)
        if err:
            return None, err
        checklist = get_checklist_by_id(checklist_id)
        if checklist is None:
            return None, _not_found(ErrorCode.CHECKLIST_NOT_FOUND, "Checklist not found.")
        return checklist, None

    @staticmethod
    def detail(checklist: Checklist, message: str) -> Response:
        """Re-read so the response carries fresh progress annotations."""
        return success_response(
            data=ChecklistDetailSerializer(get_checklist_by_id(str(checklist.id))).data,
            message=message,
        )


class ChecklistDetailView(ChecklistScopedView):
    """GET/PATCH /api/v1/checklists/<id>/."""

    def get(self, request: Request, checklist_id: str) -> Response:
        checklist, err = self.resolve(request, checklist_id)
        if err:
            return err
        return success_response(data=ChecklistDetailSerializer(checklist).data, message="Checklist retrieved.")

    def patch(self, request: Request, checklist_id: str) -> Response:
        checklist, err = self.resolve(request, checklist_id)
        if err:
            return err

        serializer = ChecklistUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        fields = dict(serializer.validated_data)

        assignee_err = _resolve_assignee(fields)
        if assignee_err:
            return assignee_err

        try:
            updated = services.update_checklist(
                actor=request.user,
                checklist=checklist,
                fields=fields,
                ip_address=_client_ip(request),
            )
        except ChecklistArchivedError as exc:
            return _conflict(ErrorCode.CHECKLIST_ARCHIVED, str(exc))
        return self.detail(updated, "Checklist updated.")


class ChecklistActivateView(ChecklistScopedView):
    """POST /api/v1/checklists/<id>/activate/."""

    def post(self, request: Request, checklist_id: str) -> Response:
        checklist, err = self.resolve(request, checklist_id)
        if err:
            return err
        try:
            updated = services.activate_checklist(
                actor=request.user,
                checklist=checklist,
                ip_address=_client_ip(request),
            )
        except ChecklistArchivedError as exc:
            return _conflict(ErrorCode.CHECKLIST_ARCHIVED, str(exc))
        except InvalidTransitionError as exc:
            return _conflict(ErrorCode.INVALID_TRANSITION, str(exc))
        return self.detail(updated, "Checklist activated.")


class ChecklistCompleteView(ChecklistScopedView):
    """POST /api/v1/checklists/<id>/complete/.

    Refuses while required work is outstanding, and names every offending item —
    "something is still pending" on a forty-item list is not an answer anyone
    can act on.
    """

    def post(self, request: Request, checklist_id: str) -> Response:
        checklist, err = self.resolve(request, checklist_id)
        if err:
            return err
        try:
            updated = services.complete_checklist(
                actor=request.user,
                checklist=checklist,
                ip_address=_client_ip(request),
            )
        except ChecklistArchivedError as exc:
            return _conflict(ErrorCode.CHECKLIST_ARCHIVED, str(exc))
        except InvalidTransitionError as exc:
            return _conflict(ErrorCode.INVALID_TRANSITION, str(exc))
        except RequiredItemsPendingError as exc:
            return _conflict(
                ErrorCode.REQUIRED_ITEMS_PENDING,
                str(exc),
                details={
                    "items": [{"id": str(item.id), "label": item.label, "status": item.status} for item in exc.items]
                },
            )
        return self.detail(updated, "Checklist completed.")


class ChecklistReopenView(ChecklistScopedView):
    """POST /api/v1/checklists/<id>/reopen/."""

    def post(self, request: Request, checklist_id: str) -> Response:
        checklist, err = self.resolve(request, checklist_id)
        if err:
            return err
        serializer = ReopenSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            updated = services.reopen_checklist(
                actor=request.user,
                checklist=checklist,
                reason=serializer.validated_data["reason"],
                ip_address=_client_ip(request),
            )
        except ChecklistArchivedError as exc:
            return _conflict(ErrorCode.CHECKLIST_ARCHIVED, str(exc))
        except InvalidTransitionError as exc:
            return _conflict(ErrorCode.INVALID_TRANSITION, str(exc))
        return self.detail(updated, "Checklist reopened.")


class ChecklistArchiveView(ChecklistScopedView):
    """POST /api/v1/checklists/<id>/archive/."""

    def post(self, request: Request, checklist_id: str) -> Response:
        checklist, err = self.resolve(request, checklist_id)
        if err:
            return err
        serializer = ArchiveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            updated = services.archive_checklist(
                actor=request.user,
                checklist=checklist,
                reason=serializer.validated_data["reason"],
                ip_address=_client_ip(request),
            )
        except ArchiveReasonRequiredError as exc:
            return _bad_request(ErrorCode.ARCHIVE_REASON_REQUIRED, str(exc), details={"reason": [str(exc)]})
        except InvalidTransitionError as exc:
            return _conflict(ErrorCode.INVALID_TRANSITION, str(exc))
        return self.detail(updated, "Checklist archived.")


class ChecklistRestoreView(ChecklistScopedView):
    """POST /api/v1/checklists/<id>/restore/."""

    def post(self, request: Request, checklist_id: str) -> Response:
        checklist, err = self.resolve(request, checklist_id)
        if err:
            return err
        try:
            updated = services.restore_checklist(
                actor=request.user,
                checklist=checklist,
                ip_address=_client_ip(request),
            )
        except ChecklistNotArchivedError as exc:
            return _conflict(ErrorCode.CHECKLIST_NOT_ARCHIVED, str(exc))
        return self.detail(updated, "Checklist restored.")


# ---------------------------------------------------------------------------
# Items
# ---------------------------------------------------------------------------


class ChecklistItemCreateView(ChecklistScopedView):
    """POST /api/v1/checklists/<id>/items/ — one extra requirement, this applicant only."""

    def post(self, request: Request, checklist_id: str) -> Response:
        checklist, err = self.resolve(request, checklist_id)
        if err:
            return err

        serializer = ChecklistItemCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)

        assignee_err = _resolve_assignee(data)
        if assignee_err:
            return assignee_err

        try:
            item = services.add_checklist_item(
                actor=request.user,
                checklist=checklist,
                data=data,
                ip_address=_client_ip(request),
            )
        except ChecklistArchivedError as exc:
            return _conflict(ErrorCode.CHECKLIST_ARCHIVED, str(exc))
        except InvalidTransitionError as exc:
            return _conflict(ErrorCode.INVALID_TRANSITION, str(exc))

        return success_response(
            data=ChecklistItemSerializer(item).data,
            message="Checklist item added.",
            http_status=status.HTTP_201_CREATED,
        )


class ChecklistItemScopedView(ChecklistScopedView):
    """Base for the two per-item routes."""

    def resolve_item(self, request: Request, checklist_id: str, item_id: str) -> tuple[Any, Response | None]:
        checklist, err = self.resolve(request, checklist_id)
        if err:
            return None, err
        item = get_item_by_id(checklist_id, item_id)
        if item is None:
            return None, _not_found(ErrorCode.ITEM_NOT_FOUND, "Checklist item not found.")
        # The item's own ``checklist`` is re-attached from the annotated read, so
        # services see the same progress-bearing instance the response will.
        item.checklist = checklist
        return item, None


class ChecklistItemDetailView(ChecklistItemScopedView):
    """PATCH /api/v1/checklists/<id>/items/<item_id>/ — descriptive fields only."""

    def patch(self, request: Request, checklist_id: str, item_id: str) -> Response:
        item, err = self.resolve_item(request, checklist_id, item_id)
        if err:
            return err

        serializer = ChecklistItemUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        fields = dict(serializer.validated_data)

        assignee_err = _resolve_assignee(fields)
        if assignee_err:
            return assignee_err

        try:
            updated = services.update_checklist_item(
                actor=request.user,
                item=item,
                fields=fields,
                ip_address=_client_ip(request),
            )
        except ChecklistArchivedError as exc:
            return _conflict(ErrorCode.CHECKLIST_ARCHIVED, str(exc))
        except InvalidTransitionError as exc:
            return _conflict(ErrorCode.INVALID_TRANSITION, str(exc))
        return success_response(data=ChecklistItemSerializer(updated).data, message="Checklist item updated.")


class ChecklistItemStatusView(ChecklistItemScopedView):
    """POST /api/v1/checklists/<id>/items/<item_id>/status/ — the daily act.

    Separate from the ``PATCH`` above, mirroring ``offers``' condition pair: the
    note requirement, the evidence check, and the completion stamps all belong to
    the status change, and a client editing a label should not have to satisfy
    them.
    """

    def post(self, request: Request, checklist_id: str, item_id: str) -> Response:
        item, err = self.resolve_item(request, checklist_id, item_id)
        if err:
            return err

        serializer = ItemStatusSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        try:
            updated = services.set_item_status(
                actor=request.user,
                item=item,
                status=data["status"],
                status_note=data.get("status_note", ""),
                evidence_file_id=data.get("evidence_file"),
                evidence_note=data.get("evidence_note", ""),
                clear_evidence=data.get("clear_evidence", False),
                ip_address=_client_ip(request),
            )
        except ChecklistArchivedError as exc:
            return _conflict(ErrorCode.CHECKLIST_ARCHIVED, str(exc))
        except InvalidTransitionError as exc:
            return _conflict(ErrorCode.INVALID_TRANSITION, str(exc))
        except StatusNoteRequiredError as exc:
            return _bad_request(ErrorCode.STATUS_NOTE_REQUIRED, str(exc), details={"status_note": [str(exc)]})
        except EvidenceNotAllowedError as exc:
            return _bad_request(ErrorCode.EVIDENCE_NOT_ALLOWED, str(exc), details={"evidence_file": [str(exc)]})

        return success_response(data=ChecklistItemSerializer(updated).data, message="Checklist item status updated.")
