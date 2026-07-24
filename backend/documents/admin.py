"""Django admin registration for the documents app (§13).

``content`` is registered read-only. It is the document body — routinely bank
balances, account numbers, and transaction histories — and an admin edit would
bypass the service layer, which is also what appends the audit event. A change
made here would alter the record and leave no trace of who did it.

There is no ``list_display`` entry for ``content`` either: the changelist would
render a wall of JSON, and the search box is scoped to labels rather than the
body for the same privacy reason the API's ``?search=`` is (see
``selectors.search_documents``).
"""

from django.contrib import admin

from documents.models import Document


@admin.register(Document)
class DocumentAdmin(admin.ModelAdmin):
    list_display = ("label", "family", "template_key", "applicant", "status", "updated_at")
    list_filter = ("status", "family")
    search_fields = ("label", "template_key")
    readonly_fields = (
        "id",
        "created_at",
        "updated_at",
        "created_by",
        "applicant",
        "family",
        "template_key",
        "content",
        "archived_at",
        "archived_by",
    )
    date_hierarchy = "updated_at"
