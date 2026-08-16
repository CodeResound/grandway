"""URL routes for the reminders app (mounted at /api/v1/reminders/)."""

from django.urls import path

from reminders.views import (
    ReminderCompleteView,
    ReminderDetailView,
    ReminderDismissView,
    ReminderHistoryView,
    ReminderListCreateView,
)

app_name = "reminders"

urlpatterns = [
    path("", ReminderListCreateView.as_view(), name="reminder-list"),
    path("<uuid:reminder_id>/", ReminderDetailView.as_view(), name="reminder-detail"),
    path("<uuid:reminder_id>/complete/", ReminderCompleteView.as_view(), name="reminder-complete"),
    path("<uuid:reminder_id>/dismiss/", ReminderDismissView.as_view(), name="reminder-dismiss"),
    path("<uuid:reminder_id>/history/", ReminderHistoryView.as_view(), name="reminder-history"),
]
