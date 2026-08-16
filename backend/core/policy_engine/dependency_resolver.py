"""Graph traversal over the endpoint dependency edges.

Both traversals here walk the same directed graph and are shaped the same way,
deliberately, because the naive shape of each is quadratic in two separate
places:

* **A query per node.** Asking the database for one endpoint's edges inside the
  walk issues one round trip per node visited (§6, N+1 prevention). Both
  functions instead expand a whole *frontier* at a time — one query per BFS
  level, so a graph of depth 3 costs three queries however wide it is.
* **``list.pop(0)`` and ``in`` against a list.** Popping the head of a Python
  list is O(n), and membership on a list is O(n) per test, so a walk over n
  nodes with e edges degrades to O(n·e). A ``deque`` and a ``set`` make both
  O(1) without changing what is computed.

Neither is hot in a request today — both run from the registry sync and
lifecycle writes — but ``sync_policy_registry`` calls
``resolve_required_permissions`` once per declared endpoint, so the cost scales
with the square of a number that only ever grows.
"""

from collections import deque

from core.policy_engine.models import PolicyDependency

#: Edge directions that count as "this endpoint points at that one".
_FORWARD_DIRECTIONS = ["forward", "bidirectional"]


def _targets_of(source_keys: list[str], **extra_filters: object) -> dict[str, list[str]]:
    """Every outgoing edge from ``source_keys``, as ``{source: [target, ...]}``.

    One query for the whole frontier. Returning a mapping rather than a flat
    list keeps the caller free to attribute an edge to the node it came from,
    which ``detect_circular_dependencies`` does not need and a future caller
    reporting *where* a cycle closes would.
    """
    if not source_keys:
        return {}

    edges = PolicyDependency.objects.filter(
        source_endpoint__permission_key__in=source_keys,
        direction__in=_FORWARD_DIRECTIONS,
        is_active=True,
        **extra_filters,
    ).values_list("source_endpoint__permission_key", "target_endpoint__permission_key")

    grouped: dict[str, list[str]] = {}
    for source, target in edges:
        grouped.setdefault(source, []).append(target)
    return grouped


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
    frontier: list[str] = [target_key]

    while frontier:
        if source_key in frontier:
            return True

        visited.update(frontier)
        grouped = _targets_of(frontier)
        next_frontier = {target for targets in grouped.values() for target in targets} - visited
        frontier = list(next_frontier)

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

    Order is breadth-first from ``permission_key`` and stable within a level
    (the database's row order for that level's edges) — the same order the
    previous queue-driven implementation produced, which callers that render
    this list to a human rely on.
    """
    required: list[str] = []
    required_seen: set[str] = set()
    visited: set[str] = set()
    frontier: deque[str] = deque([permission_key])

    while frontier:
        # Order-preserving dedup: one key can be reached twice within a level,
        # and expanding it twice would query and iterate the same edges again.
        level = list(dict.fromkeys(key for key in frontier if key not in visited))
        visited.update(level)
        frontier.clear()

        grouped = _targets_of(level, dependency_type="requires", enforcement_mode__in=enforcement_modes)
        for key in level:
            for dep_key in grouped.get(key, []):
                if dep_key not in required_seen:
                    required_seen.add(dep_key)
                    required.append(dep_key)
                frontier.append(dep_key)

    return required
