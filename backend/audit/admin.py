"""Django admin registration for the audit app (read-only, append-only)."""

from __future__ import annotations

from django.contrib import admin

from audit.models import AuditEvent


@admin.register(AuditEvent)
class AuditEventAdmin(admin.ModelAdmin):
    list_display = ("created_at", "app_label", "action", "actor_type", "actor_label", "entity_type", "success")
    list_filter = ("app_label", "actor_type", "success", "action")
    search_fields = ("actor_label", "action", "entity_type", "summary", "reason")
    readonly_fields = tuple(f.name for f in AuditEvent._meta.fields)
    ordering = ("-created_at",)

    def has_add_permission(self, request: object) -> bool:
        return False

    def has_change_permission(self, request: object, obj: object = None) -> bool:
        return False

    def has_delete_permission(self, request: object, obj: object = None) -> bool:
        return False
