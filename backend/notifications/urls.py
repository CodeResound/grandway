"""URL routes for the notifications app (mounted at /api/v1/notifications/).

One resource, and no nesting under the apps a notification points at. A route
like ``/api/v1/checklists/<id>/notifications/`` would put this app's access rule
— own-recipient only — inside another app's namespace, where every reader would
reasonably expect that app's rule instead. "Everything about this record" is
this list filtered: ``?source_entity_id=<id>``.

``read-all/`` sits above the ``<uuid:notification_id>/`` routes because it is a
collection action rather than an instance one. Django resolves in order and a
UUID converter cannot match ``read-all``, so the ordering is documentation
rather than a load-bearing detail.
"""

from django.urls import path

from notifications.views import (
    NotificationDetailView,
    NotificationDismissView,
    NotificationListView,
    NotificationReadAllView,
    NotificationReadView,
    NotificationSummaryView,
    NotificationUnreadView,
)

app_name = "notifications"

urlpatterns = [
    # The feed.
    path("", NotificationListView.as_view(), name="notification-list"),
    path("summary/", NotificationSummaryView.as_view(), name="notification-summary"),
    path("read-all/", NotificationReadAllView.as_view(), name="notification-read-all"),
    # One notification.
    path("<uuid:notification_id>/", NotificationDetailView.as_view(), name="notification-detail"),
    path("<uuid:notification_id>/read/", NotificationReadView.as_view(), name="notification-read"),
    path("<uuid:notification_id>/unread/", NotificationUnreadView.as_view(), name="notification-unread"),
    path("<uuid:notification_id>/dismiss/", NotificationDismissView.as_view(), name="notification-dismiss"),
]
