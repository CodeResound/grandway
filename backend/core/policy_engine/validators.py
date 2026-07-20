import re
from typing import Any

from core.policy_engine.constants import (
    DependencyDirection,
    DependencyType,
    EnforcementMode,
    OperationType,
    RiskLevel,
)
from core.policy_engine.exceptions import PolicyInvalidPermissionKeyError, PolicyInvalidVersionError

_PERMISSION_KEY_RE = re.compile(r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$")
_SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")

_REQUIRED_CONFIG_KEYS = ("app_key", "endpoint_key", "permission_key", "operation_type", "display_name")


def validate_permission_key_format(key: str) -> None:
    """Raise PolicyInvalidPermissionKey if key does not match app.model.action format."""
    if not _PERMISSION_KEY_RE.match(key):
        raise PolicyInvalidPermissionKeyError(
            f"Invalid permission key '{key}'. " "Must be lowercase 'app.model.action' with snake_case segments."
        )


def validate_semantic_version(version: str) -> None:
    """Raise PolicyInvalidVersion if version does not match MAJOR.MINOR.PATCH."""
    if not _SEMVER_RE.match(version):
        raise PolicyInvalidVersionError(f"Invalid version '{version}'. Must match MAJOR.MINOR.PATCH (e.g. 1.0.0).")


def validate_registry_config(config: dict[str, Any]) -> list[str]:
    """Validate one POLICY_ENDPOINTS config dict before it reaches the lifecycle.
    Returns human-readable problem strings (empty list = valid); never raises,
    so a sync run can collect every problem across all configs at once."""
    problems: list[str] = []

    for key in _REQUIRED_CONFIG_KEYS:
        if not config.get(key):
            problems.append(f"missing required key '{key}'")
    if problems:
        return problems

    permission_key: str = config["permission_key"]
    if not _PERMISSION_KEY_RE.match(permission_key):
        problems.append(
            f"permission_key '{permission_key}' is invalid — must be lowercase "
            "'app.model.action' with snake_case segments"
        )

    operation_type: str = config["operation_type"]
    if operation_type not in OperationType.values:
        problems.append(f"operation_type '{operation_type}' is not one of {sorted(OperationType.values)}")

    risk_level = config.get("risk_level", RiskLevel.LOW)
    if risk_level not in RiskLevel.values:
        problems.append(f"risk_level '{risk_level}' is not one of {sorted(RiskLevel.values)}")

    version = config.get("version", "1.0.0")
    if not isinstance(version, str) or not _SEMVER_RE.match(version):
        problems.append(f"version '{version}' is invalid — must match MAJOR.MINOR.PATCH (e.g. 1.0.0)")

    dependencies = config.get("dependencies", [])
    if not isinstance(dependencies, list):
        problems.append("'dependencies' must be a list of dicts")
        return problems

    for index, dep in enumerate(dependencies):
        if not isinstance(dep, dict):
            problems.append(f"dependencies[{index}] must be a dict")
            continue
        if not dep.get("target_permission_key"):
            problems.append(f"dependencies[{index}] is missing 'target_permission_key'")
        direction = dep.get("direction", DependencyDirection.FORWARD)
        if direction not in DependencyDirection.values:
            problems.append(
                f"dependencies[{index}] direction '{direction}' is not one of {sorted(DependencyDirection.values)}"
            )
        dep_type = dep.get("dependency_type", DependencyType.REQUIRES)
        if dep_type not in DependencyType.values:
            problems.append(
                f"dependencies[{index}] dependency_type '{dep_type}' is not one of {sorted(DependencyType.values)}"
            )
        enforcement = dep.get("enforcement_mode", EnforcementMode.STRICT)
        if enforcement not in EnforcementMode.values:
            problems.append(
                f"dependencies[{index}] enforcement_mode '{enforcement}' is not one of "
                f"{sorted(EnforcementMode.values)}"
            )

    return problems


def validate_high_risk_has_dependencies(
    permission_key: str,
    risk_level: str,
    has_dependencies: bool,
) -> list[str]:
    """Return a list of validation error strings for high/critical endpoints with no dependencies."""
    errors: list[str] = []
    if risk_level in ("high", "critical") and not has_dependencies:
        errors.append(f"Endpoint '{permission_key}' has risk_level='{risk_level}' but has no dependency metadata.")
    return errors
