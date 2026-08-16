"""Thin views for the reminders app.

Views receive the request, apply the interim access checks (§9,
``access.py``), validate input, call a service, translate domain exceptions
into the standard error envelope (§7), and shape the response. No business
logic lives here.

Access is one rule throughout: any Admin or Lead Manager, for both read and
write. Only Admins *receive* the due alert, but that is notification routing,
not an access rule here.
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

from reminders import services
from reminders.access import require_reminder_actor
from reminders.constants import ErrorCode
from reminders.exceptions import (
    ActorNotPermittedError,
    OwnerNotFoundError,
    OwnerNotResolvedError,
    ReminderAlreadyClosedError,
)
from reminders.models import Reminder
from reminders.selectors import (
    filter_reminders,
    get_history_for_reminder,
    get_reminder_by_id,
    get_reminders,
)
from reminders.serializers import (
    ReminderActionSerializer,
    ReminderCreateSerializer,
    ReminderFilterSerializer,
    ReminderSerializer,
    ReminderUpdateSerializer,
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
        ErrorCode.REMINDER_NOT_FOUND,
        "Reminder not found.",
        http_status=status.HTTP_404_NOT_FOUND,
    )


def _bad_request(code: str, message: str, details: dict[str, Any] | None = None) -> Response:
    return error_response(code, message, details=details, http_status=status.HTTP_400_BAD_REQUEST)


def _conflict(message: str) -> Response:
    return error_response(
        ErrorCode.REMINDER_ALREADY_CLOSED,
        message,
        http_status=status.HTTP_409_CONFLICT,
    )


def _paginated(request: Request, queryset: Any, serializer_class: Any, message: str) -> Response:
    paginator = StandardPagination()
    page = paginator.paginate_queryset(queryset, request)
    serializer = serializer_class(page if page is not None else queryset, many=True)
    if page is not None:
        return paginator.get_paginated_response(serializer.data)
    return success_response(data=serializer.data, message=message)


def _validated_filters(request: Request) -> dict[str, Any]:
    """Validate the query string, or raise DRF's ``ValidationError``."""
    serializer = ReminderFilterSerializer(data=request.query_params)
    serializer.is_valid(raise_exception=True)
    return serializer.validated_data


class ReminderScopedView(APIView):
    """Base for every view addressing a single reminder by id."""

    permission_classes = [IsAuthenticated]

    def resolve(self, request: Request, reminder_id: str) -> tuple[Reminder | None, Response | None]:
        try:
            require_reminder_actor(request.user)
        except ActorNotPermittedError:
            return None, _forbidden()
        reminder = get_reminder_by_id(reminder_id)
        if reminder is None:
            return None, _not_found()
        return reminder, None


class ReminderListCreateView(APIView):
    """GET/POST /api/v1/reminders/ — list follow-ups, or set a new one."""

    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        try:
            require_reminder_actor(request.user)
        except ActorNotPermittedError:
            return _forbidden()
        queryset = filter_reminders(get_reminders(), _validated_filters(request))
        return _paginated(request, queryset, ReminderSerializer, "Reminders retrieved.")

    def post(self, request: Request) -> Response:
        try:
            require_reminder_actor(request.user)
        except ActorNotPermittedError:
            return _forbidden()
        serializer = ReminderCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)

        try:
            owner = services.resolve_owner(data)
        except OwnerNotResolvedError as exc:
            return _bad_request(ErrorCode.OWNER_REQUIRED, str(exc))
        except OwnerNotFoundError as exc:
            return _bad_request(
                ErrorCode.OWNER_NOT_FOUND,
                str(exc),
                details={exc.owner_field: ["Not found."]},
            )

        reminder = services.create_reminder(
            actor=request.user,
            due_date=data["due_date"],
            note=data["note"],
            ip_address=_client_ip(request),
            **owner,
        )
        return success_response(
            data=ReminderSerializer(reminder).data,
            message="Reminder set.",
            http_status=status.HTTP_201_CREATED,
        )


class ReminderDetailView(ReminderScopedView):
    """GET/PATCH /api/v1/reminders/<id>/ — read, reschedule, or correct one reminder."""

    #: Fields a PATCH may not carry. Rejected loudly rather than dropped
    #: silently: a client that sent ``applicant`` and got 200 back would
    #: believe it had re-pointed the reminder, and the one thing this app
    #: guarantees is that it did not.
    REJECTED_ON_PATCH = frozenset({"applicant", "client", "status", "closed_at", "closed_by"})

    def get(self, request: Request, reminder_id: str) -> Response:
        reminder, err = self.resolve(request, reminder_id)
        if err:
            return err
        return success_response(data=ReminderSerializer(reminder).data, message="Reminder retrieved.")

    def patch(self, request: Request, reminder_id: str) -> Response:
        reminder, err = self.resolve(request, reminder_id)
        if err:
            return err

        attempted = sorted(self.REJECTED_ON_PATCH & set(request.data or {}))
        if attempted:
            return _bad_request(
                ErrorCode.FIELD_IMMUTABLE,
                "A reminder's owner and lifecycle fields cannot be edited.",
                details={field: ["This field cannot be changed after the reminder is set."] for field in attempted},
            )

        serializer = ReminderUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        try:
            updated = services.update_reminder(
                actor=request.user,
                reminder=reminder,
                due_date=serializer.validated_data.get("due_date"),
                note=serializer.validated_data.get("note"),
                ip_address=_client_ip(request),
            )
        except ReminderAlreadyClosedError as exc:
            return _conflict(str(exc))
        return success_response(data=ReminderSerializer(updated).data, message="Reminder updated.")


class _ReminderCloseView(ReminderScopedView):
    """Shared shape for the two terminal actions."""

    service: Any = None
    done_message = ""

    def post(self, request: Request, reminder_id: str) -> Response:
        reminder, err = self.resolve(request, reminder_id)
        if err:
            return err
        serializer = ReminderActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            closed = type(self).service(
                actor=request.user,
                reminder=reminder,
                reason=serializer.validated_data.get("reason", ""),
                ip_address=_client_ip(request),
            )
        except ReminderAlreadyClosedError as exc:
            return _conflict(str(exc))
        return success_response(data=ReminderSerializer(closed).data, message=self.done_message)


class ReminderCompleteView(_ReminderCloseView):
    """POST /api/v1/reminders/<id>/complete/ — the follow-up happened."""

    service = staticmethod(services.complete_reminder)
    done_message = "Reminder completed."


class ReminderDismissView(_ReminderCloseView):
    """POST /api/v1/reminders/<id>/dismiss/ — the follow-up is no longer relevant."""

    service = staticmethod(services.dismiss_reminder)
    done_message = "Reminder dismissed."


class ReminderHistoryView(ReminderScopedView):
    """GET /api/v1/reminders/<id>/history/ — the audit trail for one reminder."""

    def get(self, request: Request, reminder_id: str) -> Response:
        reminder, err = self.resolve(request, reminder_id)
        if err:
            return err
        return _paginated(
            request,
            get_history_for_reminder(reminder),
            AuditEventHistorySerializer,
            "History retrieved.",
        )
