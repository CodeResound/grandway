"""Django admin registration for the checklists app.

Lifecycle state is read-only: it is set by the service layer, and admin must
never bypass it (§13). That matters more here than in most apps — ``status``,
``completed_at``, and ``completed_by`` are the record that the required-items
check was satisfied, and a checklist marked complete through the admin would
carry that claim with nothing behind it.
"""

from __future__ import annotations

from django.contrib import admin

from checklists.models import Checklist, ChecklistItem, ChecklistTemplate, ChecklistTemplateItem


class ChecklistTemplateItemInline(admin.TabularInline):
    model = ChecklistTemplateItem
    extra = 0
    fields = ("label", "item_type", "is_required", "display_order", "default_due_offset_days", "is_active")


@admin.register(ChecklistTemplate)
class ChecklistTemplateAdmin(admin.ModelAdmin):
    list_display = ("label", "key", "country", "is_default", "status", "display_order")
    list_filter = ("status", "is_default", "country")
    list_select_related = ("country",)
    search_fields = ("label", "key", "country__name")
    readonly_fields = ("id", "created_by", "created_at", "updated_at")
    inlines = [ChecklistTemplateItemInline]
    ordering = ("display_order", "label")


@admin.register(ChecklistTemplateItem)
class ChecklistTemplateItemAdmin(admin.ModelAdmin):
    list_display = ("label", "template", "item_type", "is_required", "display_order", "is_active")
    list_filter = ("item_type", "is_required", "is_active")
    list_select_related = ("template",)
    search_fields = ("label", "template__label")
    readonly_fields = ("id", "created_at", "updated_at")


class ChecklistItemInline(admin.TabularInline):
    model = ChecklistItem
    extra = 0
    fields = ("label", "item_type", "is_required", "status", "due_at", "display_order")
    readonly_fields = ("status",)


@admin.register(Checklist)
class ChecklistAdmin(admin.ModelAdmin):
    list_display = ("title", "journey", "country", "origin", "status", "due_at", "created_at")
    list_filter = ("status", "origin", "country")
    list_select_related = ("journey", "journey__applicant", "country")
    search_fields = (
        "title",
        "journey__applicant__full_name",
        "country__name",
    )
    readonly_fields = (
        "id",
        "journey",
        "source_template",
        "country",
        "origin",
        "status",
        "activated_at",
        "completed_at",
        "completed_by",
        "archive_reason",
        "archived_at",
        "archived_by",
        "created_by",
        "created_at",
        "updated_at",
    )
    inlines = [ChecklistItemInline]
    ordering = ("-created_at",)


@admin.register(ChecklistItem)
class ChecklistItemAdmin(admin.ModelAdmin):
    list_display = ("label", "checklist", "item_type", "is_required", "status", "due_at")
    list_filter = ("status", "item_type", "is_required")
    list_select_related = ("checklist",)
    search_fields = ("label", "checklist__title")
    readonly_fields = (
        "id",
        "checklist",
        "source_template_item",
        "status",
        "status_note",
        "evidence_file",
        "completed_at",
        "completed_by",
        "created_at",
        "updated_at",
    )
    ordering = ("checklist", "display_order")
