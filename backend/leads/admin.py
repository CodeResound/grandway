"""Django admin registration for the leads app.

Ownership, lifecycle timestamps, and the derived romanized name are read-only:
they are set by the service layer, and admin must never bypass it (§13).
"""

from __future__ import annotations

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

    list_display = ("code", "name_np", "name_en", "requires_detail", "is_active", "display_order")
    list_filter = ("is_active", "requires_detail")
    search_fields = ("code", "name_np", "name_en", "name_romanized")
    readonly_fields = ("id", "name_romanized", "created_at", "updated_at")
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
    list_display = ("full_name_np", "full_name_en", "stage", "source", "created_by", "last_followed_up_at")
    list_filter = ("stage", "source", "lost_reason")
    search_fields = ("full_name_np", "full_name_en", "full_name_romanized", "email")
    readonly_fields = (
        "id",
        "full_name_romanized",
        "created_by",
        "last_followed_up_at",
        "last_followed_up_by",
        "lost_at",
        "lost_by",
        "stage_before_loss",
        "converted_at",
        "converted_by",
        "created_at",
        "updated_at",
    )
    inlines = [LeadContactNumberInline, LeadStudyInterestInline]
    ordering = ("-created_at",)


@admin.register(LeadNote)
class LeadNoteAdmin(admin.ModelAdmin):
    """Notes are append-only; everything on an existing note is read-only."""

    list_display = ("lead", "author", "created_at")
    search_fields = ("lead__full_name_np", "lead__full_name_en", "body")
    readonly_fields = ("id", "lead", "body", "author", "created_at", "updated_at")

    def has_delete_permission(self, request: object, obj: object | None = None) -> bool:
        return False
