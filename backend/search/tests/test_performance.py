"""Query-count regression tests for the search read path.

A grouped search is the one endpoint in this project that fans out across nine
apps, so it is also the one where an N+1 hides best: nine buckets each returning
five rows means a per-row query costs forty-five round trips and still looks
like a working endpoint. These tests pin the query count so that regression
fails a test rather than a production page.

``assertNumQueries`` is an **exact** assertion, not a ceiling, so these numbers
are the real cost and any change to it — in this app or in an owning app's
selector — fails here and has to be looked at. That is deliberate: a search that
silently doubles its query count is exactly the regression this app is most
prone to, and a loose bound would let it through. When one of these fails,
read the captured SQL in the failure output before changing the number.
"""

from __future__ import annotations

from django.test import TestCase

from search import selectors
from search.constants import SEARCHABLE_TYPE_KEYS
from search.tests.factories import (
    TOKEN,
    make_admin,
    make_applicant,
    make_lead,
    make_lead_manager,
    seed_world,
)


class TestQueryCounts(TestCase):
    def setUp(self) -> None:
        self.admin = make_admin()
        self.manager = make_lead_manager()
        self.world = seed_world(self.admin, self.manager)

    def test_a_full_search_is_a_bounded_number_of_queries(self) -> None:
        """Twenty: two per bucket, plus one prefetch each for applicants and leads.

        Nine buckets × (one count + one slice) = 18, and the applicant and lead
        buckets each add a ``contact_numbers`` prefetch because ``matched_on``
        reports phone matches. Nothing else in the app is allowed a third query.

        Without this test, adding a related field to any hit builder would
        silently turn one of the nine buckets into a per-row fetch, and a
        five-row preview would hide it completely.
        """
        with self.assertNumQueries(20):
            selectors.search_everything(actor=self.admin, query=TOKEN)

    def test_query_count_does_not_grow_with_the_number_of_results(self) -> None:
        """The N+1 test proper.

        Twenty more matching applicants must cost exactly what one did. If any
        hit field were lazily loaded, this is where it would show.
        """
        with self.assertNumQueries(3):
            selectors.search_everything(actor=self.admin, query=TOKEN, types=["applicant"])

        for index in range(20):
            make_applicant(self.admin, name=f"{TOKEN} Extra {index}", email=f"e{index}@example.com")

        with self.assertNumQueries(3):
            selectors.search_everything(actor=self.admin, query=TOKEN, types=["applicant"], limit_per_type=20)

    def test_lead_bucket_does_not_grow_with_the_number_of_results(self) -> None:
        with self.assertNumQueries(3):
            selectors.search_everything(actor=self.manager, query=TOKEN, types=["lead"])

        for index in range(20):
            make_lead(self.manager, name=f"{TOKEN} Extra {index}", number=f"98000000{index:02d}")

        with self.assertNumQueries(3):
            selectors.search_everything(actor=self.manager, query=TOKEN, types=["lead"], limit_per_type=20)

    def test_file_bucket_is_two_queries(self) -> None:
        """Files carry nine joins on the list path and none on the search path.

        The hit reads three local columns, so this bucket should be a count and
        a single-table select — no joins, no prefetches.
        """
        with self.assertNumQueries(2):
            selectors.search_everything(actor=self.admin, query=TOKEN, types=["uploaded_file"])

    def test_program_bucket_does_not_grow_with_results(self) -> None:
        with self.assertNumQueries(2):
            selectors.search_everything(actor=self.admin, query=TOKEN, types=["program"])

    def test_narrowing_types_narrows_the_work(self) -> None:
        """`?types=` is the one control a caller has over the cost of a search.

        A client that renders only the people sections must not pay for the
        catalogue and template buckets it will not show.
        """
        people_only = self._count(types=["applicant", "lead", "client"])
        everything = self._count(types=None)
        self.assertLess(people_only, everything)

    def _count(self, *, types: list[str] | None) -> int:
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        with CaptureQueriesContext(connection) as captured:
            selectors.search_everything(actor=self.admin, query=TOKEN, types=types)
        return len(captured)


class TestHitBuildersTouchNoExtraTables(TestCase):
    """Every hit builder must read only what its resolver already loaded.

    Parameterised over the whole catalogue rather than written per type, so a
    tenth searchable type is covered the day it is added. This is the test that
    would have caught ``matched_on`` reading ``applicant.passport`` before
    ``select_related("passport")`` was added.
    """

    def setUp(self) -> None:
        self.admin = make_admin()
        self.manager = make_lead_manager()
        seed_world(self.admin, self.manager)

    def test_building_hits_costs_nothing_beyond_the_slice(self) -> None:
        for key in SEARCHABLE_TYPE_KEYS:
            with self.subTest(entity_type=key):
                queryset = selectors.RESOLVERS[key](self.admin, TOKEN)
                rows = list(queryset[:5])
                build = selectors.HIT_BUILDERS[key]

                with self.assertNumQueries(0):
                    for row in rows:
                        build(row, TOKEN)
