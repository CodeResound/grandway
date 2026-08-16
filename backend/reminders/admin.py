"""Django admin registration for the reminders app (§13).

The lifecycle stamps are read-only: they are written by the service layer,
which is also what appends the audit event. An admin edit that bypassed the
service would close a reminder and leave no trace of who did it.
"""

from django.contrib import admin

from reminders.models import Reminder


@admin.register(Reminder)
class ReminderAdmin(admin.ModelAdmin):
    list_display = ("__str__", "owner_type", "due_date", "status", "created_by", "created_at")
    list_filter = ("status", "due_date")
    search_fields = ("note", "applicant__full_name", "client__name")
    readonly_fields = (
        "id",
        "created_at",
        "updated_at",
        "created_by",
        "closed_at",
        "closed_by",
    )
