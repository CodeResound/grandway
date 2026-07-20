from core.policy_engine.models import PolicyDependency


def detect_circular_dependencies(
    source_key: str,
    target_key: str,
    direction: str,
) -> bool:
    """
    Return True if adding source→target would create a circular dependency.
    Uses BFS traversal over existing forward dependencies.
    Only checks for cycles when direction is forward or bidirectional.
    """
    if direction == "backward":
        return False

    visited: set[str] = set()
    queue: list[str] = [target_key]

    while queue:
        current = queue.pop(0)
        if current == source_key:
            return True
        if current in visited:
            continue
        visited.add(current)

        next_keys = list(
            PolicyDependency.objects.filter(
                source_endpoint__permission_key=current,
                direction__in=["forward", "bidirectional"],
                is_active=True,
            ).values_list("target_endpoint__permission_key", flat=True)
        )
        queue.extend(next_keys)

    return False


def get_dependency_graph(app_key: str | None = None) -> dict:
    """
    Return the full dependency graph as an adjacency dict keyed by permission_key.
    Each value is a list of dicts with target, direction, type, and enforcement.
    """
    qs = PolicyDependency.objects.select_related("source_endpoint", "target_endpoint").filter(is_active=True)

    if app_key:
        qs = qs.filter(source_endpoint__application__key=app_key)

    graph: dict[str, list[dict]] = {}
    for dep in qs:
        src = dep.source_endpoint.permission_key
        if src not in graph:
            graph[src] = []
        graph[src].append(
            {
                "target": dep.target_endpoint.permission_key,
                "direction": dep.direction,
                "type": dep.dependency_type,
                "enforcement": dep.enforcement_mode,
            }
        )

    return graph


def resolve_required_permissions(
    permission_key: str,
    enforcement_modes: tuple[str, ...] = ("strict", "warning"),
) -> list[str]:
    """
    Recursively resolve all forward 'requires' dependencies for a given
    permission key, restricted to the given enforcement_modes (default
    preserves the original strict+warning behavior). Returns a flat list of
    all required permission keys.
    """
    required: list[str] = []
    visited: set[str] = set()
    queue: list[str] = [permission_key]

    while queue:
        current = queue.pop(0)
        if current in visited:
            continue
        visited.add(current)

        deps = PolicyDependency.objects.filter(
            source_endpoint__permission_key=current,
            dependency_type="requires",
            direction__in=["forward", "bidirectional"],
            enforcement_mode__in=enforcement_modes,
            is_active=True,
        ).values_list("target_endpoint__permission_key", flat=True)

        for dep_key in deps:
            if dep_key not in required:
                required.append(dep_key)
            queue.append(dep_key)

    return required
