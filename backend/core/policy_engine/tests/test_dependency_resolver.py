"""Traversal over the endpoint dependency graph.

``dependency_resolver`` had no direct coverage, which mattered once the two
traversals were rewritten to expand a whole BFS frontier per query instead of
one node per query. The rewrite is only safe if it computes exactly what the
node-at-a-time version did, so these tests pin both halves of that: the answers
(reachability, dedup, enforcement filtering, ordering) and the cost (one query
per level of depth, not one per node).

``add_dependency`` is used rather than building ``PolicyDependency`` rows
directly, because it is the only supported way to create an edge and it runs
``detect_circular_dependencies`` on the way in — so the cycle tests exercise the
real caller rather than a reimplementation of it.
"""

from __future__ import annotations

from django.test import TestCase

from core.policy_engine.constants import (
    DependencyDirection,
    DependencyType,
    EnforcementMode,
    OperationType,
)
from core.policy_engine.dependency_resolver import (
    detect_circular_dependencies,
    resolve_required_permissions,
)
from core.policy_engine.exceptions import PolicyCircularDependencyError
from core.policy_engine.services import (
    add_dependency,
    register_application,
    register_endpoint,
)


def make_endpoint(key: str) -> None:
    """Register one endpoint under the shared test application."""
    register_endpoint(
        app_key="app",
        endpoint_key=key.replace(".", "-"),
        permission_key=key,
        operation_type=OperationType.READ,
        display_name=key,
    )


def requires(source: str, target: str, **kwargs: object) -> None:
    """``source`` requires ``target`` — a forward, strict edge unless told otherwise."""
    add_dependency(source_permission_key=source, target_permission_key=target, **kwargs)


class ResolveRequiredPermissionsTests(TestCase):
    def setUp(self) -> None:
        register_application(key="app", display_name="App")

    def test_a_chain_resolves_transitively_in_breadth_first_order(self) -> None:
        for key in ("app.a.read", "app.b.read", "app.c.read"):
            make_endpoint(key)
        requires("app.a.read", "app.b.read")
        requires("app.b.read", "app.c.read")

        self.assertEqual(
            resolve_required_permissions("app.a.read"),
            ["app.b.read", "app.c.read"],
        )

    def test_a_diamond_lists_the_shared_dependency_once(self) -> None:
        """Two paths to the same node must not produce it twice.

        The list is rendered to a human deciding what to grant; a duplicate
        reads as two separate requirements.
        """
        for key in ("app.top.read", "app.left.read", "app.right.read", "app.base.read"):
            make_endpoint(key)
        requires("app.top.read", "app.left.read")
        requires("app.top.read", "app.right.read")
        requires("app.left.read", "app.base.read")
        requires("app.right.read", "app.base.read")

        resolved = resolve_required_permissions("app.top.read")

        self.assertEqual(resolved.count("app.base.read"), 1)
        self.assertEqual(set(resolved), {"app.left.read", "app.right.read", "app.base.read"})
        # Breadth-first: the top's own two edges precede what they lead to.
        self.assertLess(resolved.index("app.right.read"), resolved.index("app.base.read"))

    def test_an_endpoint_with_no_dependencies_resolves_to_nothing(self) -> None:
        make_endpoint("app.lonely.read")

        self.assertEqual(resolve_required_permissions("app.lonely.read"), [])

    def test_enforcement_mode_filters_the_walk(self) -> None:
        """A strict-only resolve must not follow an edge through a warning one."""
        for key in ("app.a.read", "app.b.read", "app.c.read"):
            make_endpoint(key)
        requires("app.a.read", "app.b.read", enforcement_mode=EnforcementMode.WARNING)
        requires("app.b.read", "app.c.read")

        both = resolve_required_permissions("app.a.read")
        strict_only = resolve_required_permissions("app.a.read", enforcement_modes=("strict",))

        self.assertEqual(both, ["app.b.read", "app.c.read"])
        self.assertEqual(strict_only, [])

    def test_a_non_requires_edge_is_not_a_requirement(self) -> None:
        for key in ("app.a.read", "app.b.read"):
            make_endpoint(key)
        requires("app.a.read", "app.b.read", dependency_type=DependencyType.SUGGESTS)

        self.assertEqual(resolve_required_permissions("app.a.read"), [])

    def test_an_inactive_edge_is_ignored(self) -> None:
        """Dependencies are soft-removed (§35 item 15), never deleted."""
        from core.policy_engine.models import PolicyDependency

        for key in ("app.a.read", "app.b.read"):
            make_endpoint(key)
        requires("app.a.read", "app.b.read")
        PolicyDependency.objects.update(is_active=False)

        self.assertEqual(resolve_required_permissions("app.a.read"), [])

    def test_query_count_tracks_depth_not_node_count(self) -> None:
        """Ten siblings at one level cost the same as one.

        This is the regression guard on the rewrite: a query per *node* would
        make ``sync_policy_registry`` — which resolves once per declared
        endpoint — grow with the square of the registry's size.
        """
        make_endpoint("app.root.read")
        for index in range(10):
            make_endpoint(f"app.leaf{index}.read")
            requires("app.root.read", f"app.leaf{index}.read")

        # One query for the root's frontier, one for the ten leaves' (empty) one.
        with self.assertNumQueries(2):
            resolved = resolve_required_permissions("app.root.read")

        self.assertEqual(len(resolved), 10)


class DetectCircularDependenciesTests(TestCase):
    def setUp(self) -> None:
        register_application(key="app", display_name="App")
        for key in ("app.a.read", "app.b.read", "app.c.read"):
            make_endpoint(key)

    def test_a_direct_back_edge_is_a_cycle(self) -> None:
        requires("app.a.read", "app.b.read")

        self.assertTrue(detect_circular_dependencies("app.b.read", "app.a.read", DependencyDirection.FORWARD))

    def test_a_transitive_back_edge_is_a_cycle(self) -> None:
        requires("app.a.read", "app.b.read")
        requires("app.b.read", "app.c.read")

        self.assertTrue(detect_circular_dependencies("app.c.read", "app.a.read", DependencyDirection.FORWARD))

    def test_a_self_edge_is_a_cycle(self) -> None:
        self.assertTrue(detect_circular_dependencies("app.a.read", "app.a.read", DependencyDirection.FORWARD))

    def test_an_unrelated_edge_is_not_a_cycle(self) -> None:
        requires("app.a.read", "app.b.read")

        self.assertFalse(detect_circular_dependencies("app.a.read", "app.c.read", DependencyDirection.FORWARD))

    def test_a_diamond_is_not_a_cycle(self) -> None:
        """Two paths to one node is convergence, not a loop.

        Worth its own test: a traversal that treated an already-seen node as
        proof of a cycle would reject a perfectly ordinary graph.
        """
        make_endpoint("app.d.read")
        requires("app.b.read", "app.d.read")
        requires("app.c.read", "app.d.read")

        self.assertFalse(detect_circular_dependencies("app.a.read", "app.b.read", DependencyDirection.FORWARD))

    def test_a_backward_edge_is_never_checked(self) -> None:
        requires("app.a.read", "app.b.read")

        self.assertFalse(detect_circular_dependencies("app.b.read", "app.a.read", DependencyDirection.BACKWARD))

    def test_add_dependency_refuses_to_close_a_loop(self) -> None:
        """The caller this protects, exercised end to end."""
        requires("app.a.read", "app.b.read")

        with self.assertRaises(PolicyCircularDependencyError):
            requires("app.b.read", "app.a.read")
