"""Django admin registration for the leads app.

Ownership, lifecycle timestamps, and the derived romanized name are read-only:
they are set by the service layer, and admin must never bypass it (§13).
"""

from __future__ import annotations

from typing import Any

from django.contrib import admin

from leads.models import (
    Lead,
    LeadContactNumber,
    LeadNote,
    LeadSource,
    LeadStudyInterest,
    LossReason,
)


class ReferenceEntryAdmin(admin.ModelAdmin):
    """Shared admin for the two configurable reference tables."""

    list_display = ("code", "name", "requires_detail", "is_active", "display_order")
    list_filter = ("is_active", "requires_detail")
    search_fields = ("code", "name")
    readonly_fields = ("id", "created_at", "updated_at")
    ordering = ("display_order", "code")


@admin.register(LeadSource)
class LeadSourceAdmin(ReferenceEntryAdmin):
    pass


@admin.register(LossReason)
class LossReasonAdmin(ReferenceEntryAdmin):
    pass


class LeadContactNumberInline(admin.TabularInline):
    model = LeadContactNumber
    extra = 0
    readonly_fields = ("id", "created_at", "updated_at")


class LeadStudyInterestInline(admin.StackedInline):
    model = LeadStudyInterest
    extra = 0
    readonly_fields = ("id", "created_at", "updated_at")


@admin.register(Lead)
class LeadAdmin(admin.ModelAdmin):
    list_display = ("full_name", "stage", "source", "created_by", "last_followed_up_at")
    list_filter = ("stage", "source", "lost_reason")
    search_fields = ("full_name", "email")
    readonly_fields = (
        "id",
        "created_by",
        "last_followed_up_at",
        "last_followed_up_by",
        "lost_at",
        "lost_by",
        "stage_before_loss",
        "converted_at",
        "converted_by",
        "deleted_at",
        "deleted_by",
        "delete_reason",
        "created_at",
        "updated_at",
    )
    inlines = [LeadContactNumberInline, LeadStudyInterestInline]
    ordering = ("-created_at",)

    def has_delete_permission(self, request: Any, obj: Any = None) -> bool:
        # Soft delete through DELETE /api/v1/leads/<id>/ is the only removal. A
        # hard delete here would cascade the lead's notes and erase its history.
        return False


@admin.register(LeadNote)
class LeadNoteAdmin(admin.ModelAdmin):
    """Read-only here: notes are edited and soft-deleted through the API, which audits it."""

    list_display = ("lead", "category", "author", "noted_at", "deleted_at")
    list_filter = ("category",)
    search_fields = ("lead__full_name", "body")
    readonly_fields = (
        "id",
        "lead",
        "category",
        "body",
        "noted_at",
        "author",
        "updated_by",
        "deleted_at",
        "deleted_by",
        "created_at",
        "updated_at",
    )

    def has_delete_permission(self, request: object, obj: object | None = None) -> bool:
        return False
