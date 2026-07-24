"""Thin views for the notifications app.

Seven endpoints, none of which creates, edits, or deletes a notification. That
absence is the API-level statement of the concept file's boundary rule: this app
reacts to business state, it does not own any — so there is nothing for a client
to author. The only writes a client may make are to its own read state and a
one-way move to dismissed.

**Every lookup goes through ``selectors.get_own_notification``**, which scopes by
recipient before it scopes by id. A notification belonging to somebody else comes
back ``None`` and is answered with 404, not 403 — a 403 would confirm the id
exists on another person's feed, and a notification title names an applicant and
the document they are missing. See ``access.py``.

Views receive the request, apply the interim access check (§9), validate the
filter set, call a selector or a service, translate domain exceptions into the
standard error envelope, and shape the response. No business logic lives here.
"""

from __future__ import annotations

from typing import Any

from core.pagination import StandardPagination
from core.responses import error_response, success_response
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from notifications import selectors, services
from notifications.access import require_notification_actor
from notifications.constants import DEFAULT_DUE_WITHIN_DAYS, ErrorCode
from notifications.exceptions import ActorNotPermittedError, AlreadyTerminalError
from notifications.models import Notification
from notifications.serializers import (
    BulkReadResultSerializer,
    FeedSummarySerializer,
    NotificationFilterSerializer,
    NotificationSerializer,
)


def _client_ip(request: Request) -> str | None:
    return request.META.get("REMOTE_ADDR")


def _forbidden(message: str) -> Response:
    return error_response(ErrorCode.ACTOR_FORBIDDEN, message, http_status=status.HTTP_403_FORBIDDEN)


def _not_found() -> Response:
    """The single 404 this app returns.

    One message for "no such notification" and for "that one is not yours",
    because the caller must not be able to tell them apart.
    """
    return error_response(
        ErrorCode.NOTIFICATION_NOT_FOUND,
        "No such notification on your feed.",
        http_status=status.HTTP_404_NOT_FOUND,
    )


def _search_params(request: Request) -> dict[str, Any]:
    """Validate query parameters and return only the ones actually supplied.

    The final intersection is not defensive tidying. DRF treats a query string as
    HTML input, and a ``BooleanField`` reading HTML input resolves a *missing*
    key to ``False`` rather than skipping it. Without this, every request would
    arrive carrying ``is_read=False`` and a plain ``GET /`` would silently mean
    "unread only" — the same trap ``checklists`` documented on its own filters.

    ``due_within_days`` is exempt: it carries a real default and is a horizon
    rather than a filter, so its absence means "use seven days", not "do not
    narrow".
    """
    serializer = NotificationFilterSerializer(data=request.query_params)
    serializer.is_valid(raise_exception=True)
    validated = serializer.validated_data
    supplied = {key: value for key, value in validated.items() if key in request.query_params}
    supplied["due_within_days"] = validated.get("due_within_days", DEFAULT_DUE_WITHIN_DAYS)
    return supplied


class NotificationBaseView(APIView):
    """Shared access check and lookup for every endpoint in this app."""

    permission_classes = [IsAuthenticated]

    def authorize(self, request: Request) -> Response | None:
        try:
            require_notification_actor(request.user)
        except ActorNotPermittedError as exc:
            return _forbidden(str(exc))
        return None

    def find(self, request: Request, notification_id: str) -> Notification | None:
        """This user's notification by id, or None. Never another user's."""
        return selectors.get_own_notification(request.user, notification_id)

    def render(self, request: Request, notification: Notification, message: str) -> Response:
        serializer = NotificationSerializer(notification, context=self._render_context(request))
        return success_response(data=serializer.data, message=message)

    def _render_context(self, request: Request) -> dict[str, Any]:
        """One clock and one horizon for every row in a response.

        Resolving "now" per row would let a page straddling a bucket boundary
        report two identically-due notifications in different buckets.
        """
        return {"now": timezone.now(), "due_within_days": DEFAULT_DUE_WITHIN_DAYS}


class NotificationListView(NotificationBaseView):
    """GET /api/v1/notifications/ — the caller's own alert feed.

    Paginated and filterable. Deliberately not narrowed to ``active`` by default:
    the concept file requires the alert history be preserved after the source
    issue is fixed, and defaulting to active here would put that history behind a
    parameter nobody knew to pass.
    """

    def get(self, request: Request) -> Response:
        if err := self.authorize(request):
            return err

        filters = _search_params(request)
        queryset = selectors.filter_feed(selectors.get_feed(request.user), filters)

        context = self._render_context(request)
        context["due_within_days"] = filters.get("due_within_days", DEFAULT_DUE_WITHIN_DAYS)

        paginator = StandardPagination()
        page = paginator.paginate_queryset(queryset, request)
        serializer = NotificationSerializer(page if page is not None else queryset, many=True, context=context)
        if page is not None:
            return paginator.get_paginated_response(serializer.data)
        return success_response(data=serializer.data, message="Notifications retrieved.")


class NotificationSummaryView(NotificationBaseView):
    """GET /api/v1/notifications/summary/ — unread count and grouping totals.

    Exists so a client rendering a bell badge is not forced to page the whole
    feed to produce one number. Two queries regardless of how many notifications
    the user holds.
    """

    def get(self, request: Request) -> Response:
        if err := self.authorize(request):
            return err

        filters = _search_params(request)
        summary = selectors.get_feed_summary(
            request.user,
            due_within_days=filters.get("due_within_days", DEFAULT_DUE_WITHIN_DAYS),
        )
        return success_response(
            data=FeedSummarySerializer(summary).data,
            message="Notification summary retrieved.",
        )


class NotificationDetailView(NotificationBaseView):
    """GET /api/v1/notifications/<id>/ — one notification from the caller's feed."""

    def get(self, request: Request, notification_id: str) -> Response:
        if err := self.authorize(request):
            return err
        notification = self.find(request, notification_id)
        if notification is None:
            return _not_found()
        return self.render(request, notification, "Notification retrieved.")


class NotificationReadView(NotificationBaseView):
    """POST /api/v1/notifications/<id>/read/ — mark one notification read.

    Idempotent: a second call keeps the original timestamp, because "when did
    they first see this" is the question a read receipt answers.
    """

    def post(self, request: Request, notification_id: str) -> Response:
        if err := self.authorize(request):
            return err
        notification = self.find(request, notification_id)
        if notification is None:
            return _not_found()
        return self.render(request, services.mark_read(notification), "Notification marked read.")


class NotificationUnreadView(NotificationBaseView):
    """POST /api/v1/notifications/<id>/unread/ — return one notification to unread.

    An inbox without this punishes the reflex of clicking through a list: the
    user who opens something they cannot deal with now needs a way to put it
    back.
    """

    def post(self, request: Request, notification_id: str) -> Response:
        if err := self.authorize(request):
            return err
        notification = self.find(request, notification_id)
        if notification is None:
            return _not_found()
        return self.render(request, services.mark_unread(notification), "Notification marked unread.")


class NotificationReadAllView(NotificationBaseView):
    """POST /api/v1/notifications/read-all/ — clear the caller's unread badge.

    The concept file's "bulk clear for low-priority items". Implemented as clear
    *everything unread* rather than a priority-scoped clear: a partial clear
    leaves a non-zero badge after the user asked for zero, and the button that
    does not do what it says is the one people stop trusting. Nothing is
    dismissed or resolved — reading is not deciding.
    """

    def post(self, request: Request) -> Response:
        if err := self.authorize(request):
            return err
        marked = services.mark_all_read(request.user)
        return success_response(
            data=BulkReadResultSerializer({"marked_read": marked}).data,
            message="Notifications marked read.",
        )


class NotificationDismissView(NotificationBaseView):
    """POST /api/v1/notifications/<id>/dismiss/ — decide this needs no action.

    Refuses an already-dismissed or already-resolved notification with 409 rather
    than returning a cheerful 200 for a write it did not perform: a client
    holding a stale list otherwise never learns the server disagrees with it.

    Dismissal sticks. The row keeps its dedupe key forever, so tonight's sweep
    finds it, creates nothing, and does not argue.
    """

    def post(self, request: Request, notification_id: str) -> Response:
        if err := self.authorize(request):
            return err
        notification = self.find(request, notification_id)
        if notification is None:
            return _not_found()

        try:
            dismissed = services.dismiss(notification, actor=request.user, ip_address=_client_ip(request))
        except AlreadyTerminalError as exc:
            return error_response(
                ErrorCode.ALREADY_TERMINAL,
                str(exc),
                details={"status": notification.status},
                http_status=status.HTTP_409_CONFLICT,
            )
        return self.render(request, dismissed, "Notification dismissed.")
