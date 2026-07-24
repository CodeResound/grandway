"""Core Policy Engine endpoint declarations for the notifications app (§35).

Run ``python manage.py sync_policy_registry`` after editing this file, then
``python manage.py validate_policy_engine``.

**One model, seven endpoints, and not a single ``create``, ``update`` in the
authoring sense, or ``delete``.** That shape is the concept file's boundary rule
made machine-readable: this app reacts to business state and owns none, so there
is nothing here for a client to author. The two ``update`` operations are read
state, not content.

Risk ratings are argued from what each endpoint actually does, not from its verb:

* ``notification.list`` is ``medium``, not ``low``. The feed's *metadata alone*
  says which applicants are missing financial documents and whose passports have
  lapsed — disclosure even without opening a single source record. The same call
  ``checklists.checklist.list`` already makes, for the same reason.
* ``notification.dismiss`` is ``medium``. It is the one endpoint that records a
  human decision that flagged work does not need doing, it is audited, and its
  effect is permanent: a dismissed alert holds its dedupe key forever, so no
  later sweep will raise the same condition again.
* ``notification.read``, ``mark_read``, ``mark_unread``, and ``mark_all_read``
  are ``low``. Reading is not deciding, and every one of them is reversible.
* ``notification.summary`` is ``low`` despite being derived from the same rows as
  the ``medium`` feed: it returns counts with no titles, no applicant names, and
  no source ids.

**Every dependency here is on this app's own list endpoint, and that is unusual
enough to explain.** The dashboards app declares dependencies on the apps it
reads (``checklists.checklist.list`` and so on) because a dashboard number that
cannot be drilled into is useless. This app declares none of those, because the
feed does not read those apps at request time — a notification carries its own
title, body, and ``source_api_path``, composed when it was raised. Following that
link is a separate authorization question the source app already answers. Making
``notifications.notification.list`` require ``checklists.checklist.list`` would
mean a Lead Manager who may not read checklists could not read the alert telling
them their own passport-expiry work is overdue.
"""

from typing import Any

_APP: dict[str, Any] = {
    "app_key": "notifications",
    "app_display_name": "Notifications",
    "version": "1.0.0",
    "is_internal": False,
    "category_key": "notification_management",
    "category_display_name": "Notifications",
}

_NOTIFICATION: dict[str, Any] = {
    **_APP,
    "model_key": "notification",
    "model_display_name": "Notification",
}


def _dep(target_key: str, reason: str) -> dict[str, Any]:
    return {
        "target_permission_key": target_key,
        "direction": "forward",
        "dependency_type": "requires",
        "enforcement_mode": "strict",
        "reason": reason,
    }


_LOGIN = _dep(
    "authenticate.session.login",
    "A session must be established by login before this endpoint is usable.",
)

#: Every action on a single notification requires the ability to list them.
#: Not merely conventional here: this app publishes no way to discover a
#: notification id other than the feed, so a permission to act on one without
#: the permission to list them would be unusable by construction.
_REQUIRES_LIST = _dep(
    "notifications.notification.list",
    "The feed is the only place a notification id can be discovered.",
)

_REQUIRES_READ = _dep(
    "notifications.notification.read",
    "The notification must be readable before it can be acted on.",
)

_PHASE = "notifications app initial build."


POLICY_ENDPOINTS: list[dict[str, Any]] = [
    # -----------------------------------------------------------------------
    # Reads
    # -----------------------------------------------------------------------
    # 1. The feed. Root of the graph — every other endpoint depends on it,
    #    because it is the only place an id comes from.
    {
        **_NOTIFICATION,
        "endpoint_key": "notification-list",
        "permission_key": "notifications.notification.list",
        "operation_type": "list",
        "display_name": "List Own Notifications",
        "description": (
            "The caller's own alert feed, newest first. Filter by status, read state, type, priority, "
            "source app, source record, or due bucket, and narrow by date or fiscal year. "
            "Scoped to the calling user — no authority can read another user's feed through the API."
        ),
        "http_method": "GET",
        "route_pattern": "/api/v1/notifications/",
        "view_import_path": "notifications.views.NotificationListView",
        "risk_level": "medium",
        "dependencies": [_LOGIN],
        "change_summary": "Initial registration of the notification feed endpoint.",
        "change_reason": _PHASE,
    },
    # 2. The bell badge. Counts only — no titles, no names, no ids.
    {
        **_NOTIFICATION,
        "endpoint_key": "notification-summary",
        "permission_key": "notifications.notification.summary",
        "operation_type": "custom",
        "display_name": "Read Own Notification Summary",
        "description": (
            "Unread count plus active totals by priority and by due bucket, for the calling user. "
            "Exists so a client rendering a bell badge is not forced to page the whole feed."
        ),
        "http_method": "GET",
        "route_pattern": "/api/v1/notifications/summary/",
        "view_import_path": "notifications.views.NotificationSummaryView",
        "risk_level": "low",
        "dependencies": [_LOGIN],
        "change_summary": "Initial registration of the notification summary endpoint.",
        "change_reason": _PHASE,
    },
    # 3. One notification.
    {
        **_NOTIFICATION,
        "endpoint_key": "notification-detail",
        "permission_key": "notifications.notification.read",
        "operation_type": "read",
        "display_name": "Read Own Notification",
        "description": (
            "One notification from the caller's own feed. A notification belonging to another user "
            "returns 404 rather than 403, so an id cannot be probed for existence on somebody else's feed."
        ),
        "http_method": "GET",
        "route_pattern": "/api/v1/notifications/<id>/",
        "view_import_path": "notifications.views.NotificationDetailView",
        "risk_level": "low",
        "dependencies": [_LOGIN, _REQUIRES_LIST],
        "change_summary": "Initial registration of the notification detail endpoint.",
        "change_reason": _PHASE,
    },
    # -----------------------------------------------------------------------
    # Read state — reversible, and never a decision about the work
    # -----------------------------------------------------------------------
    # 4. Mark read.
    {
        **_NOTIFICATION,
        "endpoint_key": "notification-read",
        "permission_key": "notifications.notification.mark_read",
        "operation_type": "update",
        "display_name": "Mark Notification Read",
        "description": (
            "Mark one of the caller's notifications read. Idempotent — a second call keeps the "
            "original timestamp, because the receipt answers when it was first seen. Does not "
            "change the notification's status: reading is not deciding."
        ),
        "http_method": "POST",
        "route_pattern": "/api/v1/notifications/<id>/read/",
        "view_import_path": "notifications.views.NotificationReadView",
        "risk_level": "low",
        "dependencies": [_LOGIN, _REQUIRES_LIST, _REQUIRES_READ],
        "change_summary": "Initial registration of the mark-read endpoint.",
        "change_reason": _PHASE,
    },
    # 5. Mark unread. The reverse of 4, and the reason 4 is low risk.
    {
        **_NOTIFICATION,
        "endpoint_key": "notification-unread",
        "permission_key": "notifications.notification.mark_unread",
        "operation_type": "update",
        "display_name": "Mark Notification Unread",
        "description": (
            "Return one of the caller's notifications to unread. Offered because an inbox without it "
            "punishes clicking through a list — the user who opens something they cannot deal with "
            "now needs a way to put it back."
        ),
        "http_method": "POST",
        "route_pattern": "/api/v1/notifications/<id>/unread/",
        "view_import_path": "notifications.views.NotificationUnreadView",
        "risk_level": "low",
        "dependencies": [_LOGIN, _REQUIRES_LIST, _REQUIRES_READ],
        "change_summary": "Initial registration of the mark-unread endpoint.",
        "change_reason": _PHASE,
    },
    # 6. Bulk clear. Low risk despite touching every row: nothing is dismissed
    #    or resolved, and every affected row can be individually reversed by 5.
    {
        **_NOTIFICATION,
        "endpoint_key": "notification-read-all",
        "permission_key": "notifications.notification.mark_all_read",
        "operation_type": "custom",
        "display_name": "Mark All Notifications Read",
        "description": (
            "Mark every unread notification on the caller's own feed read, and return how many changed. "
            "Clears everything unread rather than a priority-scoped subset, so the badge the user "
            "asked to clear actually reaches zero. Nothing is dismissed or resolved."
        ),
        "http_method": "POST",
        "route_pattern": "/api/v1/notifications/read-all/",
        "view_import_path": "notifications.views.NotificationReadAllView",
        "risk_level": "low",
        "dependencies": [_LOGIN, _REQUIRES_LIST],
        "change_summary": "Initial registration of the bulk mark-all-read endpoint.",
        "change_reason": _PHASE,
    },
    # -----------------------------------------------------------------------
    # The one decision this app records
    # -----------------------------------------------------------------------
    # 7. Dismiss. Audited, permanent in effect, and the only endpoint here that
    #    changes what a later sweep will do.
    {
        **_NOTIFICATION,
        "endpoint_key": "notification-dismiss",
        "permission_key": "notifications.notification.dismiss",
        "operation_type": "custom",
        "display_name": "Dismiss Notification",
        "description": (
            "Record that one of the caller's notifications needs no action. Writes an audit event. "
            "Permanent in effect: a dismissed alert keeps its deduplication key, so no later sweep "
            "raises the same condition again. Refuses an already dismissed or resolved notification."
        ),
        "http_method": "POST",
        "route_pattern": "/api/v1/notifications/<id>/dismiss/",
        "view_import_path": "notifications.views.NotificationDismissView",
        "risk_level": "medium",
        "dependencies": [_LOGIN, _REQUIRES_LIST, _REQUIRES_READ],
        "change_summary": "Initial registration of the notification dismiss endpoint.",
        "change_reason": _PHASE,
    },
]
