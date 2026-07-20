from rest_framework import serializers

from core.policy_engine.models import (
    PermissionCategory,
    PolicyApplication,
    PolicyChangeLog,
    PolicyDependency,
    PolicyEndpoint,
    PolicyEndpointVersion,
    PolicyModel,
)


class PolicyApplicationSerializer(serializers.ModelSerializer):
    class Meta:
        model = PolicyApplication
        fields = (
            "id",
            "key",
            "display_name",
            "description",
            "current_version",
            "is_active",
            "is_deprecated",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields


class PolicyModelSerializer(serializers.ModelSerializer):
    application_key = serializers.SlugRelatedField(source="application", slug_field="key", read_only=True)

    class Meta:
        model = PolicyModel
        fields = (
            "id",
            "application_key",
            "key",
            "display_name",
            "description",
            "import_path",
            "current_version",
            "is_active",
            "is_deprecated",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields


class PolicyEndpointSerializer(serializers.ModelSerializer):
    application_key = serializers.SlugRelatedField(source="application", slug_field="key", read_only=True)
    model_key = serializers.SlugRelatedField(source="policy_model", slug_field="key", read_only=True)

    class Meta:
        model = PolicyEndpoint
        fields = (
            "id",
            "application_key",
            "model_key",
            "key",
            "permission_key",
            "http_method",
            "route_pattern",
            "view_import_path",
            "operation_type",
            "display_name",
            "description",
            "current_version",
            "risk_level",
            "is_internal",
            "is_dependency_root",
            "is_active",
            "is_deprecated",
            "deprecated_at",
            "disabled_at",
            "sunset_at",
            "replaced_by_permission_key",
            "removal_ticket",
            "removal_reason",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields


class PermissionCategorySerializer(serializers.ModelSerializer):
    application_key = serializers.SlugRelatedField(source="application", slug_field="key", read_only=True)
    parent_key = serializers.SlugRelatedField(source="parent", slug_field="key", read_only=True)

    class Meta:
        model = PermissionCategory
        fields = (
            "id",
            "application_key",
            "parent_key",
            "key",
            "display_name",
            "description",
            "icon_key",
            "sort_order",
            "is_active",
            "is_deprecated",
        )
        read_only_fields = fields


class PolicyDependencySerializer(serializers.ModelSerializer):
    source_permission_key = serializers.CharField(source="source_endpoint.permission_key", read_only=True)
    target_permission_key = serializers.CharField(source="target_endpoint.permission_key", read_only=True)

    class Meta:
        model = PolicyDependency
        fields = (
            "id",
            "source_permission_key",
            "target_permission_key",
            "direction",
            "dependency_type",
            "enforcement_mode",
            "reason",
            "is_active",
            "is_deprecated",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields


class PolicyEndpointVersionSerializer(serializers.ModelSerializer):
    permission_key = serializers.CharField(source="endpoint.permission_key", read_only=True)
    # Currency is derived, not stored — see PolicyEndpointVersion's docstring.
    is_current = serializers.SerializerMethodField()

    def get_is_current(self, obj: PolicyEndpointVersion) -> bool:
        return obj.version == obj.endpoint.current_version

    class Meta:
        model = PolicyEndpointVersion
        fields = (
            "id",
            "permission_key",
            "version",
            "route_pattern",
            "http_method",
            "view_import_path",
            "operation_type",
            "snapshot",
            "is_current",
            "is_deprecated",
            "created_at",
        )
        read_only_fields = fields


class PolicyChangeLogSerializer(serializers.ModelSerializer):
    application_key = serializers.SlugRelatedField(source="application", slug_field="key", read_only=True)

    class Meta:
        model = PolicyChangeLog
        fields = (
            "id",
            "application_key",
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
            "branch_name",
            "based_on_commit_sha",
            "affected_dependencies",
            "affected_categories",
            "backward_compatibility_notes",
            "forward_compatibility_notes",
            "created_by_type",
            "created_by_identifier",
            "created_at",
        )
        read_only_fields = fields


class PolicyApplicationDetailSerializer(serializers.ModelSerializer):
    policy_models = PolicyModelSerializer(many=True, read_only=True)
    endpoints = PolicyEndpointSerializer(many=True, read_only=True)

    class Meta:
        model = PolicyApplication
        fields = (
            "id",
            "key",
            "display_name",
            "description",
            "current_version",
            "is_active",
            "is_deprecated",
            "created_at",
            "updated_at",
            "policy_models",
            "endpoints",
        )
        read_only_fields = fields
