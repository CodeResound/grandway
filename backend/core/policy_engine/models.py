from django.db import models

from core.models import BaseModel
from core.policy_engine.constants import (
    ChangeType,
    CreatedByType,
    DependencyDirection,
    DependencyType,
    EnforcementMode,
    ObjectType,
    OperationType,
    RiskLevel,
)


class AppendOnlyQuerySet(models.QuerySet):
    """QuerySet that blocks bulk mutations on append-only models."""

    def update(self, **kwargs):
        raise _immutability_error(self.model, "bulk-updated")

    def delete(self):
        raise _immutability_error(self.model, "bulk-deleted")


class AppendOnlyManager(models.Manager):
    def get_queryset(self) -> AppendOnlyQuerySet:
        return AppendOnlyQuerySet(self.model, using=self._db)


def _immutability_error(model, operation: str):
    from core.policy_engine.exceptions import PolicyImmutabilityError

    return PolicyImmutabilityError(
        f"{model.__name__} records are append-only and cannot be {operation}. "
        "The policy engine audit trail is immutable."
    )


class PolicyApplication(BaseModel):
    key = models.SlugField(max_length=100, unique=True, db_index=True)
    display_name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    current_version = models.CharField(max_length=50, default="1.0.0")
    is_active = models.BooleanField(default=True)
    is_deprecated = models.BooleanField(default=False)

    class Meta:
        ordering = ["key"]
        verbose_name = "Policy Application"
        verbose_name_plural = "Policy Applications"

    def __str__(self) -> str:
        return self.key


class PolicyModel(BaseModel):
    application = models.ForeignKey(
        PolicyApplication,
        on_delete=models.CASCADE,
        related_name="policy_models",
    )
    key = models.SlugField(max_length=100, db_index=True)
    import_path = models.CharField(max_length=500, blank=True)
    display_name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    current_version = models.CharField(max_length=50, default="1.0.0")
    is_active = models.BooleanField(default=True)
    is_deprecated = models.BooleanField(default=False)

    class Meta:
        unique_together = ("application", "key")
        ordering = ["application__key", "key"]
        verbose_name = "Policy Model"
        verbose_name_plural = "Policy Models"

    def __str__(self) -> str:
        return f"{self.application.key}.{self.key}"


class PolicyEndpoint(BaseModel):
    application = models.ForeignKey(
        PolicyApplication,
        on_delete=models.CASCADE,
        related_name="endpoints",
    )
    policy_model = models.ForeignKey(
        PolicyModel,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="endpoints",
    )
    key = models.SlugField(max_length=100, db_index=True)
    permission_key = models.CharField(max_length=255, unique=True, db_index=True)
    http_method = models.CharField(max_length=20, blank=True)
    route_pattern = models.CharField(max_length=500, blank=True)
    view_import_path = models.CharField(max_length=500, blank=True)
    operation_type = models.CharField(max_length=50, choices=OperationType.choices)
    display_name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    current_version = models.CharField(max_length=50, default="1.0.0")
    risk_level = models.CharField(
        max_length=50,
        choices=RiskLevel.choices,
        default=RiskLevel.LOW,
    )
    is_internal = models.BooleanField(default=False)
    is_dependency_root = models.BooleanField(
        default=False,
        help_text=(
            "True for endpoints that legitimately have no prerequisite permission "
            "(e.g. login) — exempts a high/critical-risk endpoint from the "
            "'must declare a dependency' validation rule."
        ),
    )
    is_active = models.BooleanField(default=True)
    is_deprecated = models.BooleanField(default=False)
    # Denormalized current-state retirement metadata. The append-only
    # PolicyChangeLog remains the authoritative event history; these fields hold
    # only the CURRENT lifecycle state so audit queries ("deprecated before X",
    # "not yet replaced", "sunset passed") are plain field reads instead of a
    # changelog scan. Set/cleared by deprecate_endpoint/disable_endpoint/
    # restore_endpoint in services.py — see DATA_CONTRACT.md §3 lifecycle rule.
    deprecated_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When deprecate_endpoint() last marked this endpoint deprecated (cleared on restore).",
    )
    disabled_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When disable_endpoint() last set is_active=False (cleared on restore).",
    )
    sunset_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Planned removal date announced at deprecation time (caller-provided; cleared on restore).",
    )
    replaced_by_permission_key = models.CharField(
        max_length=255,
        blank=True,
        help_text="permission_key of the successor endpoint, if any. Loose pointer — the successor "
        "may not be registered yet, so this is not a ForeignKey.",
    )
    removal_ticket = models.CharField(
        max_length=255,
        blank=True,
        help_text="External tracker reference for the removal, if a ticketing convention exists.",
    )
    removal_reason = models.TextField(
        blank=True,
        help_text="Why this endpoint is being retired (cleared on restore).",
    )

    class Meta:
        unique_together = ("application", "key")
        ordering = ["application__key", "key"]
        verbose_name = "Policy Endpoint"
        verbose_name_plural = "Policy Endpoints"

    def __str__(self) -> str:
        return self.permission_key


class PermissionCategory(BaseModel):
    application = models.ForeignKey(
        PolicyApplication,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="categories",
    )
    policy_model = models.ForeignKey(
        PolicyModel,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="categories",
    )
    parent = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="children",
    )
    key = models.SlugField(max_length=100, unique=True, db_index=True)
    display_name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    icon_key = models.CharField(max_length=100, blank=True)
    sort_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    is_deprecated = models.BooleanField(default=False)

    class Meta:
        ordering = ["sort_order", "key"]
        verbose_name = "Permission Category"
        verbose_name_plural = "Permission Categories"

    def __str__(self) -> str:
        return self.key


class EndpointCategoryMap(BaseModel):
    endpoint = models.ForeignKey(
        PolicyEndpoint,
        on_delete=models.CASCADE,
        related_name="category_maps",
    )
    category = models.ForeignKey(
        PermissionCategory,
        on_delete=models.CASCADE,
        related_name="endpoint_maps",
    )
    display_label = models.CharField(max_length=255)
    help_text = models.TextField(blank=True)
    sort_order = models.PositiveIntegerField(default=0)
    is_visible_in_ui = models.BooleanField(default=True)
    is_sensitive = models.BooleanField(default=False)

    class Meta:
        unique_together = ("endpoint", "category")
        ordering = ["sort_order"]
        verbose_name = "Endpoint Category Map"
        verbose_name_plural = "Endpoint Category Maps"

    def __str__(self) -> str:
        return f"{self.endpoint.permission_key} → {self.category.key}"


class PolicyEndpointVersion(BaseModel):
    """Immutable history record. Currency is derived, never stored: a version
    record is "current" iff its version equals endpoint.current_version."""

    objects = AppendOnlyManager()

    # PROTECT prevents cascade-deletion of version history when an endpoint is deleted.
    # Use deprecate_endpoint() instead of deleting endpoints that have version records.
    endpoint = models.ForeignKey(
        PolicyEndpoint,
        on_delete=models.PROTECT,
        related_name="versions",
    )
    version = models.CharField(max_length=50)
    route_pattern = models.CharField(max_length=500, blank=True)
    http_method = models.CharField(max_length=20, blank=True)
    view_import_path = models.CharField(max_length=500, blank=True)
    operation_type = models.CharField(max_length=50)
    snapshot = models.JSONField(default=dict, blank=True)
    is_deprecated = models.BooleanField(default=False)

    class Meta:
        unique_together = ("endpoint", "version")
        ordering = ["-created_at"]
        verbose_name = "Policy Endpoint Version"
        verbose_name_plural = "Policy Endpoint Versions"

    def __str__(self) -> str:
        return f"{self.endpoint.permission_key}@{self.version}"

    def save(self, *args, **kwargs) -> None:
        if not self._state.adding:
            raise _immutability_error(self.__class__, "updated")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs) -> None:
        raise _immutability_error(self.__class__, "deleted")


class PolicyDependency(BaseModel):
    source_endpoint = models.ForeignKey(
        PolicyEndpoint,
        on_delete=models.CASCADE,
        related_name="outgoing_dependencies",
    )
    target_endpoint = models.ForeignKey(
        PolicyEndpoint,
        on_delete=models.CASCADE,
        related_name="incoming_dependencies",
    )
    direction = models.CharField(max_length=50, choices=DependencyDirection.choices)
    dependency_type = models.CharField(max_length=50, choices=DependencyType.choices)
    enforcement_mode = models.CharField(
        max_length=50,
        choices=EnforcementMode.choices,
        default=EnforcementMode.STRICT,
    )
    reason = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    is_deprecated = models.BooleanField(default=False)

    class Meta:
        unique_together = ("source_endpoint", "target_endpoint", "direction", "dependency_type")
        ordering = ["source_endpoint__permission_key", "target_endpoint__permission_key"]
        verbose_name = "Policy Dependency"
        verbose_name_plural = "Policy Dependencies"

    def __str__(self) -> str:
        return (
            f"{self.source_endpoint.permission_key} "
            f"-{self.dependency_type}→ "
            f"{self.target_endpoint.permission_key}"
        )


class PolicyChangeLog(BaseModel):
    objects = AppendOnlyManager()

    # PROTECT: you cannot delete a PolicyApplication, PolicyModel, or PolicyEndpoint
    # that has changelog entries. Use deprecation instead of deletion.
    application = models.ForeignKey(
        PolicyApplication,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="changelogs",
    )
    policy_model = models.ForeignKey(
        PolicyModel,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="changelogs",
    )
    endpoint = models.ForeignKey(
        PolicyEndpoint,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="changelogs",
    )
    object_type = models.CharField(max_length=50, choices=ObjectType.choices)
    object_key = models.CharField(max_length=255, blank=True)
    previous_version = models.CharField(max_length=50, blank=True)
    new_version = models.CharField(max_length=50, blank=True)
    change_type = models.CharField(max_length=100, choices=ChangeType.choices)
    summary = models.CharField(max_length=500)
    detail = models.TextField(blank=True)
    reason = models.TextField(blank=True)
    issue_reference = models.CharField(max_length=255, blank=True)
    migration_reference = models.CharField(max_length=255, blank=True)
    branch_name = models.CharField(max_length=255, blank=True)
    based_on_commit_sha = models.CharField(max_length=40, blank=True)
    affected_dependencies = models.JSONField(default=list, blank=True)
    affected_categories = models.JSONField(default=list, blank=True)
    backward_compatibility_notes = models.TextField(blank=True)
    forward_compatibility_notes = models.TextField(blank=True)
    created_by_type = models.CharField(
        max_length=50,
        choices=CreatedByType.choices,
        default=CreatedByType.SYSTEM,
    )
    created_by_identifier = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Policy Change Log"
        verbose_name_plural = "Policy Change Logs"

    def __str__(self) -> str:
        return f"{self.change_type}: {self.object_key} ({self.created_at})"

    def save(self, *args, **kwargs) -> None:
        if not self._state.adding:
            raise _immutability_error(self.__class__, "updated")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs) -> None:
        raise _immutability_error(self.__class__, "deleted")
