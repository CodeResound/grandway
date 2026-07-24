"""Django admin registration for the document_templates app (§13).

Both models are registered for inspection with their identity fields read-only.
``key`` in particular: documents point at it as a plain string with no foreign
key behind them, so an admin rename would orphan every document that used it,
silently — and would bypass the service layer that appends the audit event, so
nothing would record who did it.

Delete is disabled on both. A signatory frozen into a snapshot's render context
and a template a document names must stay resolvable forever; retirement is a
status change, which the changelist exposes as a filter rather than an action.
"""

from typing import Any

from django.contrib import admin
from django.http import HttpRequest

from document_templates.models import DocumentTemplate, Signatory


class _NoDeleteAdmin(admin.ModelAdmin):
    """Registration for a table whose rows are retired, never removed."""

    def has_delete_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return False


@admin.register(Signatory)
class SignatoryAdmin(_NoDeleteAdmin):
    list_display = ("name", "role", "status", "updated_at")
    list_filter = ("status", "role")
    search_fields = ("name",)
    readonly_fields = ("id", "created_by", "created_at", "updated_at")

    def get_queryset(self, request: HttpRequest) -> Any:
        return super().get_queryset(request).select_related("created_by")


@admin.register(DocumentTemplate)
class DocumentTemplateAdmin(_NoDeleteAdmin):
    list_display = ("key", "family", "label", "display_order", "status", "updated_at")
    list_filter = ("family", "status")
    search_fields = ("key", "label")
    # ``key`` is read-only for the reason in the module docstring.
    readonly_fields = ("id", "key", "created_by", "created_at", "updated_at")

    def get_queryset(self, request: HttpRequest) -> Any:
        return super().get_queryset(request).select_related("created_by")
