from django.db import models


class OperationType(models.TextChoices):
    CREATE = "create", "Create"
    READ = "read", "Read"
    LIST = "list", "List"
    UPDATE = "update", "Update"
    DELETE = "delete", "Delete"
    CUSTOM = "custom", "Custom"


class RiskLevel(models.TextChoices):
    LOW = "low", "Low"
    MEDIUM = "medium", "Medium"
    HIGH = "high", "High"
    CRITICAL = "critical", "Critical"


class DependencyDirection(models.TextChoices):
    FORWARD = "forward", "Forward"
    BACKWARD = "backward", "Backward"
    BIDIRECTIONAL = "bidirectional", "Bidirectional"


class DependencyType(models.TextChoices):
    REQUIRES = "requires", "Requires"
    IMPLIES = "implies", "Implies"
    CONFLICTS_WITH = "conflicts_with", "Conflicts With"
    REVOKES_WITH = "revokes_with", "Revokes With"
    SUGGESTS = "suggests", "Suggests"


class EnforcementMode(models.TextChoices):
    STRICT = "strict", "Strict"
    WARNING = "warning", "Warning"
    MANUAL_REVIEW = "manual_review", "Manual Review"
    METADATA_ONLY = "metadata_only", "Metadata Only"


class ChangeType(models.TextChoices):
    CREATED = "created", "Created"
    UPDATED = "updated", "Updated"
    BUG_FIX = "bug_fix", "Bug Fix"
    SECURITY_FIX = "security_fix", "Security Fix"
    ROUTE_CHANGED = "route_changed", "Route Changed"
    METHOD_CHANGED = "method_changed", "Method Changed"
    DEPENDENCY_ADDED = "dependency_added", "Dependency Added"
    DEPENDENCY_REMOVED = "dependency_removed", "Dependency Removed"
    CATEGORY_CHANGED = "category_changed", "Category Changed"
    DEPRECATED = "deprecated", "Deprecated"
    REMOVED = "removed", "Removed"
    RESTORED = "restored", "Restored"
    BREAKING_CHANGE = "breaking_change", "Breaking Change"
    METADATA_UPDATE = "metadata_update", "Metadata Update"


class CreatedByType(models.TextChoices):
    HUMAN = "human", "Human"
    AI = "ai", "AI"
    SYSTEM = "system", "System"


class ObjectType(models.TextChoices):
    APPLICATION = "application", "Application"
    MODEL = "model", "Model"
    ENDPOINT = "endpoint", "Endpoint"
    CATEGORY = "category", "Category"
    DEPENDENCY = "dependency", "Dependency"


class PolicyEngineErrorCode:
    ENDPOINT_NOT_FOUND = "POLICY_ENGINE_ENDPOINT_NOT_FOUND"
    APPLICATION_NOT_FOUND = "POLICY_ENGINE_APPLICATION_NOT_FOUND"
    MODEL_NOT_FOUND = "POLICY_ENGINE_MODEL_NOT_FOUND"
    CATEGORY_NOT_FOUND = "POLICY_ENGINE_CATEGORY_NOT_FOUND"
    DUPLICATE_KEY = "POLICY_ENGINE_DUPLICATE_KEY"
    CIRCULAR_DEPENDENCY = "POLICY_ENGINE_CIRCULAR_DEPENDENCY"
    LIFECYCLE_INCOMPLETE = "POLICY_ENGINE_LIFECYCLE_INCOMPLETE"
    INVALID_PERMISSION_KEY = "POLICY_ENGINE_INVALID_PERMISSION_KEY"
    INVALID_VERSION = "POLICY_ENGINE_INVALID_VERSION"
    VALIDATION_FAILED = "POLICY_ENGINE_VALIDATION_FAILED"
