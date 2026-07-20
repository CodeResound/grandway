from django.contrib import admin

from core.policy_engine.models import (
    EndpointCategoryMap,
    PermissionCategory,
    PolicyApplication,
    PolicyChangeLog,
    PolicyDependency,
    PolicyEndpoint,
    PolicyEndpointVersion,
    PolicyModel,
)


@admin.register(PolicyApplication)
class PolicyApplicationAdmin(admin.ModelAdmin):
    list_display = ("key", "display_name", "current_version", "is_active", "is_deprecated", "created_at")
    list_filter = ("is_active", "is_deprecated")
    search_fields = ("key", "display_name")
    readonly_fields = ("id", "created_at", "updated_at")
    ordering = ("key",)


@admin.register(PolicyModel)
class PolicyModelAdmin(admin.ModelAdmin):
    list_display = ("__str__", "display_name", "current_version", "is_active", "is_deprecated", "created_at")
    list_filter = ("application", "is_active", "is_deprecated")
    search_fields = ("key", "display_name", "application__key")
    readonly_fields = ("id", "created_at", "updated_at")
    ordering = ("application__key", "key")


@admin.register(PolicyEndpoint)
class PolicyEndpointAdmin(admin.ModelAdmin):
    list_display = (
        "permission_key",
        "application",
        "operation_type",
        "risk_level",
        "current_version",
        "is_active",
        "is_deprecated",
        "is_internal",
        "is_dependency_root",
    )
    list_filter = (
        "application",
        "operation_type",
        "risk_level",
        "is_active",
        "is_deprecated",
        "is_internal",
        "is_dependency_root",
    )
    search_fields = ("permission_key", "key", "display_name", "route_pattern")
    # Lifecycle metadata is set only by the deprecate/disable/restore services —
    # read-only here so the admin can inspect but never bypass those transitions (§13).
    readonly_fields = (
        "id",
        "created_at",
        "updated_at",
        "deprecated_at",
        "disabled_at",
        "sunset_at",
        "replaced_by_permission_key",
        "removal_ticket",
        "removal_reason",
    )
    ordering = ("application__key", "key")


@admin.register(PermissionCategory)
class PermissionCategoryAdmin(admin.ModelAdmin):
    list_display = ("key", "display_name", "application", "sort_order", "is_active", "is_deprecated")
    list_filter = ("application", "is_active", "is_deprecated")
    search_fields = ("key", "display_name")
    readonly_fields = ("id", "created_at", "updated_at")
    ordering = ("sort_order", "key")


@admin.register(EndpointCategoryMap)
class EndpointCategoryMapAdmin(admin.ModelAdmin):
    list_display = ("endpoint", "category", "display_label", "sort_order", "is_visible_in_ui", "is_sensitive")
    list_filter = ("category", "is_visible_in_ui", "is_sensitive")
    search_fields = ("endpoint__permission_key", "category__key", "display_label")
    readonly_fields = ("id", "created_at", "updated_at")


@admin.register(PolicyEndpointVersion)
class PolicyEndpointVersionAdmin(admin.ModelAdmin):
    list_display = ("__str__", "endpoint", "version", "is_deprecated", "created_at")
    list_filter = ("is_deprecated",)
    search_fields = ("endpoint__permission_key", "version")
    readonly_fields = (
        "id",
        "endpoint",
        "version",
        "route_pattern",
        "http_method",
        "view_import_path",
        "operation_type",
        "snapshot",
        "is_deprecated",
        "created_at",
        "updated_at",
    )
    ordering = ("-created_at",)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(PolicyDependency)
class PolicyDependencyAdmin(admin.ModelAdmin):
    list_display = (
        "source_endpoint",
        "target_endpoint",
        "direction",
        "dependency_type",
        "enforcement_mode",
        "is_active",
        "is_deprecated",
    )
    list_filter = ("direction", "dependency_type", "enforcement_mode", "is_active", "is_deprecated")
    search_fields = ("source_endpoint__permission_key", "target_endpoint__permission_key")
    readonly_fields = ("id", "created_at", "updated_at")


@admin.register(PolicyChangeLog)
class PolicyChangeLogAdmin(admin.ModelAdmin):
    list_display = (
        "object_key",
        "object_type",
        "change_type",
        "created_by_type",
        "created_by_identifier",
        "created_at",
    )
    list_filter = ("object_type", "change_type", "created_by_type", "application")
    search_fields = ("object_key", "summary", "created_by_identifier")
    readonly_fields = (
        "id",
        "application",
        "policy_model",
        "endpoint",
        "object_type",
        "object_key",
        "previous_version",
        "new_version",
        "change_type",
        "summary",
        "detail",
        "reason",
        "issue_reference",
        "migration_reference",
        "affected_dependencies",
        "affected_categories",
        "backward_compatibility_notes",
        "forward_compatibility_notes",
        "created_by_type",
        "created_by_identifier",
        "created_at",
        "updated_at",
    )
    ordering = ("-created_at",)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
