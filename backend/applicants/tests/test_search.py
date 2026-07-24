"""Applicant list search, relevance ranking, and destination filtering.

Separate from ``test_applicants.py`` because these cases need cross-app fixtures
— a country from ``institutions`` and a journey from ``applicant_journeys`` —
that no other applicant test requires. The applicant record itself holds no
destination; the whole point of the filters exercised here is that they reach
through the reverse ``journeys`` accessor to find one.
"""

from __future__ import annotations

from typing import Any

from applicant_journeys import services as journey_services
from applicant_journeys.constants import JourneyStage
from django.urls import reverse
from institutions.tests.factories import make_country
from rest_framework import status
from rest_framework.test import APITestCase

from applicants import services
from applicants.tests.factories import make_admin, make_applicant, token_for


class ApplicantSearchTestCase(APITestCase):
    def setUp(self) -> None:
        self.admin = make_admin()
        self.list_url = reverse("v1:applicants:applicant-list")
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token_for(self.admin)}")

    def names(self, response: Any) -> list[str]:
        return [row["full_name"] for row in response.data["data"]]


class TestMultiFieldSearch(ApplicantSearchTestCase):
    """``?search=`` reaches past the name into email, phone, and passport."""

    def setUp(self) -> None:
        super().setUp()
        self.target = services.create_applicant(
            actor=self.admin,
            data={
                "full_name": "Ram Shrestha",
                "email": "ram.shrestha@example.com",
            },
            contact_numbers=[{"number": "9841000111", "label": "mobile", "is_primary": True}],
            passport={"passport_number": "PA1234567"},
        )
        self.other = make_applicant(self.admin, full_name="Sita Gurung")

    def test_search_matches_email(self) -> None:
        resp = self.client.get(self.list_url, {"search": "ram.shrestha@example.com"})
        self.assertEqual(resp.data["meta"]["count"], 1)
        self.assertEqual(resp.data["data"][0]["id"], str(self.target.id))

    def test_search_matches_partial_contact_number(self) -> None:
        """A number read off a call log is often partial."""
        resp = self.client.get(self.list_url, {"search": "9841000"})
        self.assertEqual(resp.data["meta"]["count"], 1)
        self.assertEqual(resp.data["data"][0]["id"], str(self.target.id))

    def test_search_matches_passport_number(self) -> None:
        resp = self.client.get(self.list_url, {"search": "PA1234567"})
        self.assertEqual(resp.data["meta"]["count"], 1)
        self.assertEqual(resp.data["data"][0]["id"], str(self.target.id))

    def test_search_matches_the_other_applicant_by_name(self) -> None:
        """Name search still works alongside the widened email/phone/passport match."""
        resp = self.client.get(self.list_url, {"search": "Sita"})
        self.assertEqual(resp.data["meta"]["count"], 1)
        self.assertEqual(resp.data["data"][0]["id"], str(self.other.id))

    def test_non_matching_query_returns_nothing(self) -> None:
        resp = self.client.get(self.list_url, {"search": "nobody-by-this-name"})
        self.assertEqual(resp.data["meta"]["count"], 0)

    def test_multiple_contact_numbers_do_not_duplicate_the_row(self) -> None:
        """The reverse-FK join would otherwise return one row per number."""
        services.update_applicant(
            actor=self.admin,
            applicant=self.target,
            fields={},
            contact_numbers=[
                {"number": "9841000111", "label": "mobile", "is_primary": True},
                {"number": "9841000222", "label": "mobile", "is_primary": False},
                {"number": "9841000333", "label": "home", "is_primary": False},
            ],
        )
        resp = self.client.get(self.list_url, {"search": "984100"})
        self.assertEqual(resp.data["meta"]["count"], 1)


class TestSearchRanking(ApplicantSearchTestCase):
    """An exact match must outrank a partial one regardless of creation order.

    Every applicant here is created oldest-exact-first, so a result set still
    ordered by ``-created_at`` would come back in exactly the reverse of the
    expected order — the assertion cannot pass by accident.
    """

    def setUp(self) -> None:
        super().setUp()
        self.exact = make_applicant(self.admin, full_name="Ram")
        self.prefix = make_applicant(self.admin, full_name="Ram Bahadur")
        self.contains = make_applicant(self.admin, full_name="Shree Ram Shrestha")

    def test_exact_beats_prefix_beats_contains(self) -> None:
        resp = self.client.get(self.list_url, {"search": "Ram"})
        self.assertEqual(
            [row["id"] for row in resp.data["data"]],
            [str(self.exact.id), str(self.prefix.id), str(self.contains.id)],
        )

    def test_name_match_beats_a_non_name_match(self) -> None:
        """Someone whose *email* contains the query sorts below every name match."""
        by_email = services.create_applicant(
            actor=self.admin,
            data={"full_name": "Hari Thapa", "email": "ram@example.com"},
            contact_numbers=[{"number": "9800000123", "label": "mobile", "is_primary": True}],
        )
        resp = self.client.get(self.list_url, {"search": "Ram"})
        ids = [row["id"] for row in resp.data["data"]]
        self.assertEqual(ids[-1], str(by_email.id))
        self.assertEqual(len(ids), 4)

    def test_unsearched_list_keeps_newest_first(self) -> None:
        """Ranking must not leak into a list with no query."""
        resp = self.client.get(self.list_url)
        self.assertEqual(
            [row["id"] for row in resp.data["data"]],
            [str(self.contains.id), str(self.prefix.id), str(self.exact.id)],
        )


class TestDestinationFilters(ApplicantSearchTestCase):
    """Country and stage live on the journey, not the applicant."""

    def setUp(self) -> None:
        super().setUp()
        self.australia = make_country(self.admin, code="au", name="Australia")
        self.canada = make_country(self.admin, code="ca", name="Canada")

        self.bound_for_au = make_applicant(self.admin, full_name="Ram Shrestha")
        self.au_journey = journey_services.create_journey(
            actor=self.admin,
            applicant=self.bound_for_au,
            data={"target_country_ref": self.australia},
        )

        self.bound_for_ca = make_applicant(self.admin, full_name="Sita Gurung")
        journey_services.create_journey(
            actor=self.admin,
            applicant=self.bound_for_ca,
            data={"target_country_ref": self.canada},
        )

        # No journey at all — must never appear under any destination filter.
        self.undecided = make_applicant(self.admin, full_name="Hari Thapa")

    def test_filter_by_country_id(self) -> None:
        resp = self.client.get(self.list_url, {"country": str(self.australia.id)})
        self.assertEqual(resp.data["meta"]["count"], 1)
        self.assertEqual(resp.data["data"][0]["id"], str(self.bound_for_au.id))

    def test_filter_by_country_code_is_case_insensitive(self) -> None:
        """A client holding 'AU' should not have to know how it was stored."""
        resp = self.client.get(self.list_url, {"country_code": "AU"})
        self.assertEqual(resp.data["meta"]["count"], 1)
        self.assertEqual(resp.data["data"][0]["id"], str(self.bound_for_au.id))

    def test_applicant_with_no_journey_is_excluded(self) -> None:
        resp = self.client.get(self.list_url, {"country_code": "ca"})
        returned = [row["id"] for row in resp.data["data"]]
        self.assertNotIn(str(self.undecided.id), returned)

    def test_two_journeys_to_one_country_return_one_row(self) -> None:
        """A person may pursue the same destination twice; they are still one person."""
        journey_services.create_journey(
            actor=self.admin,
            applicant=self.bound_for_au,
            data={"target_country_ref": self.australia},
        )
        resp = self.client.get(self.list_url, {"country": str(self.australia.id)})
        self.assertEqual(resp.data["meta"]["count"], 1)

    def test_filter_by_journey_stage(self) -> None:
        journey_services.change_stage(
            actor=self.admin,
            journey=self.au_journey,
            stage=JourneyStage.PROFILE_BUILDING,
        )
        resp = self.client.get(self.list_url, {"journey_stage": JourneyStage.PROFILE_BUILDING})
        self.assertEqual(resp.data["meta"]["count"], 1)
        self.assertEqual(resp.data["data"][0]["id"], str(self.bound_for_au.id))

    def test_country_filter_composes_with_search(self) -> None:
        """Filters narrow the same data rather than replacing one another."""
        resp = self.client.get(self.list_url, {"country_code": "au", "search": "Sita"})
        self.assertEqual(resp.data["meta"]["count"], 0)

    def test_unknown_country_returns_empty_not_error(self) -> None:
        resp = self.client.get(self.list_url, {"country_code": "zz"})
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["meta"]["count"], 0)


class TestDestinationsResponseField(ApplicantSearchTestCase):
    """The list response carries where each person is trying to go."""

    def setUp(self) -> None:
        super().setUp()
        self.australia = make_country(self.admin, code="au", name="Australia")
        self.applicant = make_applicant(self.admin, full_name="Ram Shrestha")

    def test_catalogue_destination_is_projected(self) -> None:
        journey = journey_services.create_journey(
            actor=self.admin,
            applicant=self.applicant,
            data={"target_country_ref": self.australia},
        )
        resp = self.client.get(self.list_url)
        destinations = resp.data["data"][0]["destinations"]
        self.assertEqual(len(destinations), 1)
        self.assertEqual(destinations[0]["journey_id"], str(journey.id))
        self.assertEqual(destinations[0]["country_id"], str(self.australia.id))
        self.assertEqual(destinations[0]["country_code"], "au")
        self.assertEqual(destinations[0]["country_name"], "Australia")
        self.assertEqual(destinations[0]["stage"], JourneyStage.PLANNING)

    def test_free_text_destination_survives_with_no_catalogue_link(self) -> None:
        """A journey recorded before the catalogue existed has only its typed name."""
        journey_services.create_journey(
            actor=self.admin,
            applicant=self.applicant,
            data={"target_country": "Australia"},
        )
        resp = self.client.get(self.list_url)
        destination = resp.data["data"][0]["destinations"][0]
        self.assertIsNone(destination["country_id"])
        self.assertEqual(destination["country_code"], "")
        self.assertEqual(destination["target_country"], "Australia")

    def test_applicant_with_no_journey_reports_an_empty_list(self) -> None:
        resp = self.client.get(self.list_url)
        self.assertEqual(resp.data["data"][0]["destinations"], [])

    def test_detail_response_carries_destinations_too(self) -> None:
        journey_services.create_journey(
            actor=self.admin,
            applicant=self.applicant,
            data={"target_country_ref": self.australia},
        )
        resp = self.client.get(reverse("v1:applicants:applicant-detail", args=[self.applicant.id]))
        self.assertEqual(len(resp.data["data"]["destinations"]), 1)
