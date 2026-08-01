"""Unit tests for the search composition layer.

These cover the invariants that hold the catalogue-driven design together. They
are cheap and they fail loudly, which is the point: the design's weakness is
that a searchable type is described in three places — the catalogue, the
resolver map, and the hit-builder map — and nothing in Python requires the three
to agree. These tests do.
"""

from __future__ import annotations

from django.test import SimpleTestCase, TestCase

from search import selectors
from search.constants import SEARCHABLE_TYPE_KEYS, SEARCHABLE_TYPES
from search.tests.factories import TOKEN, make_admin, make_lead_manager, seed_world


class TestCatalogueInvariants(SimpleTestCase):
    """No database needed — these are checks on the declarations themselves."""

    def test_every_catalogue_type_has_a_resolver(self) -> None:
        self.assertEqual(set(selectors.RESOLVERS), set(SEARCHABLE_TYPE_KEYS))

    def test_every_catalogue_type_has_a_hit_builder(self) -> None:
        self.assertEqual(set(selectors.HIT_BUILDERS), set(SEARCHABLE_TYPE_KEYS))

    def test_type_keys_are_unique(self) -> None:
        self.assertEqual(len(SEARCHABLE_TYPE_KEYS), len(set(SEARCHABLE_TYPE_KEYS)))

    def test_every_detail_path_has_an_id_placeholder(self) -> None:
        """Without it, every hit of that type would link to the list."""
        for entry in SEARCHABLE_TYPES:
            with self.subTest(entity_type=entry.key):
                self.assertIn("{id}", entry.detail_path)

    def test_permission_keys_follow_app_model_action(self) -> None:
        """§35 item 4 — the format the policy engine registers against."""
        for entry in SEARCHABLE_TYPES:
            with self.subTest(entity_type=entry.key):
                for key in (entry.detail_permission_key, entry.list_permission_key):
                    self.assertEqual(len(key.split(".")), 3, key)
                    self.assertEqual(key, key.lower())

    def test_list_search_param_is_one_of_the_two_the_project_uses(self) -> None:
        for entry in SEARCHABLE_TYPES:
            with self.subTest(entity_type=entry.key):
                self.assertIn(entry.list_search_param, {"search", "q"})


class TestMatchedOn(SimpleTestCase):
    def test_reports_only_fields_containing_the_query(self) -> None:
        matched = selectors._matched_on("ram", [("full_name", "Ram Thapa"), ("email", "x@example.com")])
        self.assertEqual(matched, ["full_name"])

    def test_is_case_insensitive(self) -> None:
        self.assertEqual(selectors._matched_on("RAM", [("full_name", "ram thapa")]), ["full_name"])

    def test_empty_is_a_legitimate_answer(self) -> None:
        """A program matched through its institution has no matching field of its own."""
        self.assertEqual(selectors._matched_on("melbourne", [("title", "Master of IT")]), [])

    def test_none_valued_fields_do_not_raise(self) -> None:
        self.assertEqual(selectors._matched_on("ram", [("email", None)]), [])


class TestSearchEverything(TestCase):
    def setUp(self) -> None:
        self.admin = make_admin()
        self.manager = make_lead_manager()
        self.world = seed_world(self.admin, self.manager)

    def test_returns_every_bucket_by_default(self) -> None:
        result = selectors.search_everything(actor=self.admin, query=TOKEN)
        self.assertEqual([b["entity_type"] for b in result["results"]], list(SEARCHABLE_TYPE_KEYS))

    def test_types_are_returned_in_catalogue_order_not_request_order(self) -> None:
        """Honouring the caller's order would let two clients render differently."""
        result = selectors.search_everything(actor=self.admin, query=TOKEN, types=["signatory", "applicant"])
        self.assertEqual([b["entity_type"] for b in result["results"]], ["applicant", "signatory"])

    def test_limit_per_type_bounds_each_bucket_independently(self) -> None:
        result = selectors.search_everything(actor=self.admin, query=TOKEN, limit_per_type=1)
        for bucket in result["results"]:
            with self.subTest(entity_type=bucket["entity_type"]):
                self.assertLessEqual(len(bucket["hits"]), 1)

    def test_unknown_type_is_dropped_rather_than_raising(self) -> None:
        """The serializer rejects unknown keys before this point; a direct
        caller gets an empty selection rather than an exception."""
        result = selectors.search_everything(actor=self.admin, query=TOKEN, types=["wombat"])
        self.assertEqual(result["results"], [])

    def test_is_known_type(self) -> None:
        self.assertTrue(selectors.is_known_type("applicant"))
        self.assertFalse(selectors.is_known_type("wombat"))
