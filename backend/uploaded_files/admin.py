"""Django admin registration for the uploaded_files app (§13).

**Everything is read-only, including for a superuser.** This is the only admin
in the project registered with no editable field at all, and the reason is the
one rule the whole app rests on: a file's metadata describes bytes that are
already on disk. An admin who could edit ``checksum_sha256``, ``size_bytes``, or
``content_type`` would be able to make the row disagree with the file it
describes, silently and with nothing to detect it afterwards.

``has_delete_permission`` returns False for the same reason it does nowhere
else: there is no deletion anywhere in this app, and the admin must not be the
one hole in that.

What the admin is *for* here is operations: finding a file by checksum or
filename, seeing which files are waiting for review, and reading the lifecycle
columns of a record a client is complaining about. All four of those are reads.
"""

from typing import Any

from django.contrib import admin
from django.http import HttpRequest

from uploaded_files.models import UploadedFile


@admin.register(UploadedFile)
class UploadedFileAdmin(admin.ModelAdmin):
    list_display = (
        "original_filename",
        "category",
        "owner_type_label",
        "version_number",
        "verification_status",
        "is_current",
        "is_archived",
        "created_at",
    )
    list_filter = ("category", "verification_status", "upload_source")
    search_fields = ("original_filename", "checksum_sha256")
    ordering = ("-created_at",)
    # Every field, computed or stored. See the module docstring.
    readonly_fields = tuple(field.name for field in UploadedFile._meta.fields) + (
        "owner_type_label",
        "is_current",
        "is_archived",
        "is_verified",
    )
    list_select_related = (
        "applicant",
        "journey",
        "offer",
        "document",
        "snapshot",
        "uploaded_by",
    )

    def has_add_permission(self, request: HttpRequest) -> bool:
        """No. A file record without bytes behind it is a lie in the table."""
        return False

    def has_change_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        """No. Lifecycle changes go through the API so they are audited."""
        return False

    def has_delete_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        """No. Nothing in this app is ever deleted, by anyone."""
        return False
