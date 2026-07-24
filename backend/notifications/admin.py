"""Django admin registration for the notifications app (§13).

This is the **only** place in the system where one person can look at another
person's notification feed. The API is own-recipient only by design
(``access.py``), and that rule would be pointless if it merely pushed
cross-user inspection somewhere less visible. Here it is a deliberate act by a
named superuser, on a screen that is not part of anybody's daily workflow.

Everything is read-only. Notifications are produced by the sweep and the signal
receivers and consumed by their recipient; an operator hand-editing a title or
flipping a status would be writing a record of something that never happened,
and the append-only alert history the concept file asks for would stop being
evidence of anything.
"""

from __future__ import annotations

from typing import Any

from django.contrib import admin
from django.http import HttpRequest

from notifications.models import Notification


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "recipient",
        "notification_type",
        "priority",
        "status",
        "due_at",
        "read_at",
        "created_at",
    )
    list_filter = ("notification_type", "priority", "status", "generated_by", "delivery_state", "source_app")
    search_fields = ("title", "body", "dedupe_key", "recipient__username")
    # ``recipient`` and ``dismissed_by`` are raw id fields rather than dropdowns:
    # a select rendering every user is one query and a very long list on a page
    # that is already the least-used in the system.
    raw_id_fields = ("recipient", "dismissed_by")
    date_hierarchy = "created_at"
    ordering = ("-created_at", "-id")

    # Every field, including the internal ones the API withholds. An operator
    # who has come this far is diagnosing something, and ``dedupe_key`` is the
    # first thing worth seeing when the question is "why was this not raised
    # again".
    readonly_fields = tuple(field.name for field in Notification._meta.fields)

    def get_queryset(self, request: HttpRequest) -> Any:
        """Join the recipient — ``list_display`` names it on every row (§6, N+1)."""
        return super().get_queryset(request).select_related("recipient", "dismissed_by")

    def has_add_permission(self, request: HttpRequest) -> bool:
        """No. A notification is raised by the sweep or a signal, never by hand.

        A hand-written alert would carry no dedupe key anybody could reason
        about, and the next sweep would be unable to resolve it.
        """
        return False

    def has_change_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        """No. Editing an alert rewrites the record of what somebody was told."""
        return False

    def has_delete_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        """No. The concept file requires the alert history survive the fix."""
        return False
