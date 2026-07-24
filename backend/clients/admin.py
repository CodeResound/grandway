"""Django admin registration for the clients app (§13).

The romanized search fields and the retirement stamp are read-only: both are
written by the service layer, which is also what appends the audit event. An
admin edit that bypassed the service would change the record and leave no trace
of who did it.
"""

from django.contrib import admin

from clients.models import Client, ClientContactNumber


class ClientContactNumberInline(admin.TabularInline):
    model = ClientContactNumber
    extra = 0
    fields = ("number", "label", "is_primary")


@admin.register(Client)
class ClientAdmin(admin.ModelAdmin):
    list_display = ("name", "email", "status", "updated_at")
    list_filter = ("status",)
    search_fields = (
        "name",
        "spokesperson_name",
        "email",
    )
    readonly_fields = (
        "id",
        "created_at",
        "updated_at",
        "created_by",
        "retired_at",
        "retired_by",
    )
    inlines = [ClientContactNumberInline]


@admin.register(ClientContactNumber)
class ClientContactNumberAdmin(admin.ModelAdmin):
    list_display = ("number", "client", "label", "is_primary")
    list_filter = ("label", "is_primary")
    search_fields = ("number", "client__name")
    readonly_fields = ("id", "created_at", "updated_at")
