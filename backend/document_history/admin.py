"""Django admin registration for the document_history app (§13).

**Everything is read-only, and nothing can be added or deleted here.** That is
not the usual "sensitive fields are read-only" caution applied to a normal
model — it is the module's entire premise. ``concepts/document_history.txt``:
"No editing of existing snapshots", "No deletion of historical snapshots". The
models enforce it too (``save``/``delete`` raise ``SnapshotImmutableError``), so
an admin edit would surface as a 500 rather than a silent corruption; the
permission hooks below turn that into a UI that never offers the action.

``content`` and ``render_context`` are excluded from ``list_display`` and from
``search_fields`` for the same privacy reason ``documents`` excludes its body:
the changelist would render a wall of JSON holding bank balances and account
numbers, and a search box over it would make personal financial data queryable
by substring.
"""

from typing import Any

from django.contrib import admin
from django.http import HttpRequest

from document_history.models import DocumentSnapshot, PrintEvent


class _ReadOnlyAdmin(admin.ModelAdmin):
    """Inspect-only registration for an append-only table."""

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_change_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return False

    def has_delete_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return False


@admin.register(DocumentSnapshot)
class DocumentSnapshotAdmin(_ReadOnlyAdmin):
    list_display = ("label", "version_number", "family", "template_key", "captured_by", "created_at")
    list_filter = ("family",)
    search_fields = ("label", "template_key")
    date_hierarchy = "created_at"
    readonly_fields = (
        "id",
        "document",
        "version_number",
        "family",
        "template_key",
        "label",
        "content",
        "render_context",
        "capture_note",
        "captured_by",
        "created_at",
        "updated_at",
    )

    def get_queryset(self, request: HttpRequest) -> Any:
        return super().get_queryset(request).select_related("captured_by")


@admin.register(PrintEvent)
class PrintEventAdmin(_ReadOnlyAdmin):
    list_display = ("event_type", "snapshot", "document", "performed_by", "created_at")
    list_filter = ("event_type",)
    date_hierarchy = "created_at"
    readonly_fields = (
        "id",
        "snapshot",
        "document",
        "event_type",
        "note",
        "performed_by",
        "created_at",
        "updated_at",
    )

    def get_queryset(self, request: HttpRequest) -> Any:
        return super().get_queryset(request).select_related("snapshot", "document", "performed_by")
