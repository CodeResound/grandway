"""Search endpoints: access, validation, envelopes, scoping, and result shape.

The suite is organised around the one property that matters most for this app:
**search must never widen access.** ``TestSearchScoping`` is the reason the rest
exists — everything else is the standard endpoint battery (§18).
"""

from __future__ import annotations

from typing import Any

from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from search.constants import (
    DEFAULT_LIMIT_PER_TYPE,
    MAX_LIMIT_PER_TYPE,
    SEARCHABLE_TYPE_KEYS,
    ErrorCode,
)
from search.tests.factories import (
    TOKEN,
    make_admin,
    make_applicant,
    make_lead,
    make_lead_manager,
    make_superadmin,
    pdf_upload,
    seed_world,
    token_for,
)

QUERY_URL = reverse("v1:search:search-query")
TYPES_URL = reverse("v1:search:search-types")


class SearchApiTestCase(APITestCase):
    def setUp(self) -> None:
        self.admin = make_admin()
        self.manager = make_lead_manager()
        self.superadmin = make_superadmin()

    def auth(self, user: Any) -> None:
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token_for(user)}")

    def search(self, **params: Any) -> Any:
        return self.client.get(QUERY_URL, params)

    def buckets(self, response: Any) -> dict[str, Any]:
        """Buckets by ``entity_type``, so assertions do not depend on order."""
        return {bucket["entity_type"]: bucket for bucket in response.data["data"]["results"]}


# ---------------------------------------------------------------------------
# Access (§18: auth failure, permission failure)
# ---------------------------------------------------------------------------


class TestSearchAccess(SearchApiTestCase):
    def test_both_endpoints_require_authentication(self) -> None:
        for url in (QUERY_URL, TYPES_URL):
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url, {"q": TOKEN}).status_code, status.HTTP_401_UNAUTHORIZED)

    def test_superadmin_is_forbidden(self) -> None:
        """A platform authority does not participate in consultancy operations."""
        self.auth(self.superadmin)
        for url in (QUERY_URL, TYPES_URL):
            with self.subTest(url=url):
                resp = self.client.get(url, {"q": TOKEN})
                self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)
                self.assertEqual(resp.data["error"]["code"], ErrorCode.ACTOR_FORBIDDEN)

    def test_admin_and_lead_manager_may_both_search(self) -> None:
        for user in (self.admin, self.manager):
            with self.subTest(user=user.username):
                self.auth(user)
                self.assertEqual(self.search(q=TOKEN).status_code, status.HTTP_200_OK)


# ---------------------------------------------------------------------------
# Validation (§18: validation failure, invalid input)
# ---------------------------------------------------------------------------


class TestSearchValidation(SearchApiTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.auth(self.admin)

    def test_query_is_required(self) -> None:
        resp = self.search()
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("q", resp.data["error"]["details"])

    def test_single_character_query_is_refused(self) -> None:
        """A one-character `icontains` is nine scans returning nothing usable."""
        resp = self.search(q="a")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("q", resp.data["error"]["details"])

    def test_whitespace_only_query_is_refused_as_too_short(self) -> None:
        """Length is checked after stripping — three spaces is not a query."""
        resp = self.search(q="   ")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_unknown_type_is_rejected_rather_than_ignored(self) -> None:
        """Silently dropping it would look exactly like 'nothing matched'."""
        resp = self.search(q=TOKEN, types="applicant,wombat")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("types", resp.data["error"]["details"])

    def test_limit_per_type_is_capped(self) -> None:
        """The cap is what stops search being an export surface."""
        resp = self.search(q=TOKEN, limit_per_type=MAX_LIMIT_PER_TYPE + 1)
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("limit_per_type", resp.data["error"]["details"])

    def test_zero_limit_per_type_is_refused(self) -> None:
        self.assertEqual(self.search(q=TOKEN, limit_per_type=0).status_code, status.HTTP_400_BAD_REQUEST)


# ---------------------------------------------------------------------------
# Envelope and shape (§18: standard response/error envelope consistency)
# ---------------------------------------------------------------------------


class TestSearchEnvelope(SearchApiTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.auth(self.admin)

    def test_success_envelope(self) -> None:
        resp = self.search(q=TOKEN)
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertTrue(resp.data["success"])
        self.assertEqual(resp.data["message"], "Search results retrieved.")
        self.assertEqual(set(resp.data["data"]), {"query", "types", "total_hits", "results"})
        self.assertEqual(resp.data["meta"], {})

    def test_error_envelope(self) -> None:
        resp = self.search(q="a")
        self.assertFalse(resp.data["success"])
        self.assertEqual(set(resp.data["error"]), {"code", "message", "details"})

    def test_every_bucket_is_returned_even_when_empty(self) -> None:
        """The client decides what to render; the API does not pre-judge.

        'No applicant by that name' is frequently the answer someone needed.
        """
        resp = self.search(q="nothingmatchesthis")
        self.assertEqual(set(self.buckets(resp)), set(SEARCHABLE_TYPE_KEYS))
        self.assertEqual(resp.data["data"]["total_hits"], 0)

    def test_bucket_shape(self) -> None:
        resp = self.search(q=TOKEN)
        bucket = self.buckets(resp)["applicant"]
        self.assertEqual(
            set(bucket),
            {"entity_type", "label", "group", "total", "has_more", "hits", "list_url", "list_permission_key"},
        )

    def test_buckets_come_back_in_catalogue_order(self) -> None:
        """Section order is the app's, so two clients cannot render it differently."""
        resp = self.search(q=TOKEN)
        returned = [bucket["entity_type"] for bucket in resp.data["data"]["results"]]
        self.assertEqual(returned, list(SEARCHABLE_TYPE_KEYS))


# ---------------------------------------------------------------------------
# Results (§18: success case, business rule)
# ---------------------------------------------------------------------------


class TestSearchResults(SearchApiTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.world = seed_world(self.admin, self.manager)
        self.auth(self.admin)

    def test_one_query_reaches_every_searchable_type(self) -> None:
        """The whole point of the app, asserted once."""
        buckets = self.buckets(self.search(q=TOKEN))
        for key in SEARCHABLE_TYPE_KEYS:
            with self.subTest(entity_type=key):
                self.assertGreaterEqual(buckets[key]["total"], 1, f"{key} bucket found nothing")

    def test_hit_carries_what_a_result_row_needs(self) -> None:
        hit = self.buckets(self.search(q=TOKEN))["applicant"]["hits"][0]
        self.assertEqual(
            set(hit),
            {"entity_type", "id", "title", "subtitle", "matched_on", "detail_path", "detail_permission_key"},
        )
        self.assertEqual(hit["id"], str(self.world["applicant"].id))
        self.assertEqual(hit["detail_path"], f"/api/v1/applicants/{self.world['applicant'].id}/")
        self.assertEqual(hit["detail_permission_key"], "applicants.applicant.read")

    def test_matched_on_names_the_field_that_matched(self) -> None:
        """A person found by phone number must not look like a name match."""
        make_applicant(self.admin, name="Bishnu Karki", email="bishnu@example.com")
        hit = self.buckets(self.search(q="bishnu@example.com"))["applicant"]["hits"][0]
        self.assertIn("email", hit["matched_on"])
        self.assertNotIn("full_name", hit["matched_on"])

    def test_list_url_uses_each_app_s_own_search_parameter(self) -> None:
        """Seven apps read `search`; the catalogue reads `q`.

        Getting this wrong returns the whole unfiltered list behind 'see all',
        which reads as a search bug rather than a bad link.
        """
        buckets = self.buckets(self.search(q=TOKEN))
        self.assertEqual(buckets["applicant"]["list_url"], f"/api/v1/applicants/?search={TOKEN}")
        self.assertEqual(buckets["institution"]["list_url"], f"/api/v1/catalogue/institutions/?q={TOKEN}")
        self.assertEqual(buckets["program"]["list_url"], f"/api/v1/catalogue/programs/?q={TOKEN}")

    def test_list_url_encodes_the_query(self) -> None:
        """A name with a space is ordinary; an unencoded one truncates the filter."""
        bucket = self.buckets(self.search(q="Ram Bahadur"))["applicant"]
        self.assertEqual(bucket["list_url"], "/api/v1/applicants/?search=Ram+Bahadur")

    def test_types_narrows_which_buckets_are_built(self) -> None:
        resp = self.search(q=TOKEN, types="applicant,lead")
        self.assertEqual(set(self.buckets(resp)), {"applicant", "lead"})

    def test_total_is_the_real_count_not_the_preview_length(self) -> None:
        """`has_more` must be derived from the full queryset, not the slice."""
        for index in range(DEFAULT_LIMIT_PER_TYPE + 2):
            make_applicant(self.admin, name=f"{TOKEN} Number {index}", email=f"a{index}@example.com")

        bucket = self.buckets(self.search(q=TOKEN))["applicant"]
        self.assertEqual(len(bucket["hits"]), DEFAULT_LIMIT_PER_TYPE)
        self.assertGreater(bucket["total"], DEFAULT_LIMIT_PER_TYPE)
        self.assertTrue(bucket["has_more"])

    def test_total_hits_sums_every_bucket(self) -> None:
        data = self.search(q=TOKEN).data["data"]
        self.assertEqual(data["total_hits"], sum(bucket["total"] for bucket in data["results"]))

    def test_exact_name_match_outranks_a_partial_one(self) -> None:
        """Inherited from `rank_applicants`; asserted here because the preview
        is five rows deep and an unranked search would bury the exact match."""
        make_applicant(self.admin, name="Sita", email="sita@example.com")
        for index in range(6):
            make_applicant(self.admin, name=f"Sitaram Number {index}", email=f"s{index}@example.com")

        hits = self.buckets(self.search(q="Sita"))["applicant"]["hits"]
        self.assertEqual(hits[0]["title"], "Sita")


# ---------------------------------------------------------------------------
# Scoping — the property this app must never break
# ---------------------------------------------------------------------------


class TestSearchScoping(SearchApiTestCase):
    """Search must never return a row the owning app would have withheld.

    ``dashboards`` shipped exactly this defect in its activity feed: a Lead
    Manager refused by the audit endpoint with a 403 was served the same rows by
    the dashboard with a 200. These tests are the standing check that the same
    thing has not happened here.
    """

    def setUp(self) -> None:
        super().setUp()
        self.world = seed_world(self.admin, self.manager)
        self.other_manager = make_lead_manager(username="othermgr")

    def test_a_lead_manager_does_not_find_another_manager_s_lead(self) -> None:
        self.auth(self.other_manager)
        buckets = self.buckets(self.search(q=TOKEN))
        self.assertEqual(buckets["lead"]["total"], 0)
        self.assertEqual(buckets["lead"]["hits"], [])

    def test_the_owning_lead_manager_does_find_their_own_lead(self) -> None:
        """The other half of the assertion — scoping, not a broken bucket."""
        self.auth(self.manager)
        buckets = self.buckets(self.search(q=TOKEN))
        self.assertEqual(buckets["lead"]["total"], 1)
        self.assertEqual(buckets["lead"]["hits"][0]["id"], str(self.world["lead"].id))

    def test_an_admin_finds_every_manager_s_lead(self) -> None:
        self.auth(self.admin)
        self.assertEqual(self.buckets(self.search(q=TOKEN))["lead"]["total"], 1)

    def test_a_lead_manager_does_not_find_an_admin_only_document_file(self) -> None:
        """Files owned by a document are outside a Lead Manager's visibility.

        ``uploaded_files.get_visible_files`` excludes them; this asserts search
        did not become a side door around that rule.
        """
        from uploaded_files.tests.factories import upload_for

        upload_for(self.admin, "document", self.world["document"], upload=pdf_upload(f"{TOKEN}-secret.pdf"))

        self.auth(self.admin)
        admin_total = self.buckets(self.search(q=f"{TOKEN}-secret"))["uploaded_file"]["total"]
        self.assertEqual(admin_total, 1)

        self.auth(self.manager)
        manager_total = self.buckets(self.search(q=f"{TOKEN}-secret"))["uploaded_file"]["total"]
        self.assertEqual(manager_total, 0)

    def test_a_lead_manager_does_not_find_a_signature_file(self) -> None:
        """The same rule, for the newest Admin-only owner type.

        A signature image is not applicant data, so it would be easy to assume
        search may surface it. It may not: ``document_templates`` refuses a Lead
        Manager on every route, and a signature is the most forgeable artefact
        in the system.
        """
        from document_templates.tests.factories import make_signatory
        from uploaded_files.tests.factories import upload_for

        signatory = make_signatory(self.admin)
        upload_for(self.admin, "signatory", signatory, upload=pdf_upload(f"{TOKEN}-signature.pdf"))

        self.auth(self.admin)
        self.assertEqual(self.buckets(self.search(q=f"{TOKEN}-signature"))["uploaded_file"]["total"], 1)

        self.auth(self.manager)
        self.assertEqual(self.buckets(self.search(q=f"{TOKEN}-signature"))["uploaded_file"]["total"], 0)

    def test_two_authorities_legitimately_see_different_totals(self) -> None:
        """Documented in `docs/API.md` §1 so it is not reported as a bug."""
        self.auth(self.admin)
        admin_total = self.search(q=TOKEN).data["data"]["total_hits"]
        self.auth(self.other_manager)
        manager_total = self.search(q=TOKEN).data["data"]["total_hits"]
        self.assertGreater(admin_total, manager_total)


# ---------------------------------------------------------------------------
# The catalogue endpoint
# ---------------------------------------------------------------------------


class TestSearchableTypes(SearchApiTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.auth(self.admin)

    def test_catalogue_lists_every_searchable_type(self) -> None:
        resp = self.client.get(TYPES_URL)
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual([row["key"] for row in resp.data["data"]], list(SEARCHABLE_TYPE_KEYS))

    def test_catalogue_row_shape(self) -> None:
        row = self.client.get(TYPES_URL).data["data"][0]
        self.assertEqual(
            set(row),
            {
                "key",
                "label",
                "group",
                "app_label",
                "matched_fields",
                "detail_path",
                "detail_permission_key",
                "list_path",
                "list_search_param",
                "list_permission_key",
            },
        )

    def test_catalogue_types_are_exactly_the_types_the_query_accepts(self) -> None:
        """A client builds its filter chips from this; a mismatch is a dead chip."""
        keys = [row["key"] for row in self.client.get(TYPES_URL).data["data"]]
        resp = self.search(q=TOKEN, types=",".join(keys))
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(set(self.buckets(resp)), set(keys))


# ---------------------------------------------------------------------------
# Owner-scoped leads, without the full world
# ---------------------------------------------------------------------------


class TestLeadScopingIsolated(SearchApiTestCase):
    """The lead scoping again, on a fixture that has nothing but leads.

    Kept separate from ``TestSearchScoping`` so a failure points at the lead
    rule rather than at any of the eight other types in the seeded world.
    """

    def setUp(self) -> None:
        super().setUp()
        self.mine = make_lead(self.manager, name="Sita Rai", number="9812345678")
        self.theirs = make_lead(self.admin, name="Sita Thapa", number="9887654321")

    def test_manager_sees_only_their_own(self) -> None:
        self.auth(self.manager)
        bucket = self.buckets(self.search(q="Sita"))["lead"]
        self.assertEqual([hit["id"] for hit in bucket["hits"]], [str(self.mine.id)])

    def test_admin_sees_both(self) -> None:
        self.auth(self.admin)
        bucket = self.buckets(self.search(q="Sita"))["lead"]
        self.assertEqual(bucket["total"], 2)

    def test_a_lead_is_findable_by_contact_number(self) -> None:
        """A lead is very often a number in a call log before a spelling."""
        self.auth(self.manager)
        bucket = self.buckets(self.search(q="9812345678"))["lead"]
        self.assertEqual(bucket["total"], 1)
        self.assertIn("contact_number", bucket["hits"][0]["matched_on"])
