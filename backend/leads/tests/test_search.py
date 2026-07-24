"""Lead list search and relevance ranking.

The mirror of ``applicants/tests/test_search.py``, minus the destination cases:
a lead's countries of interest live in a ``JSONField`` that cannot be filtered
portably, so there is no destination filter to test (``docs/INTEGRATION.md`` §9).

The owner-scoping case matters most here. Ranking reorders rows; it must never
widen which rows a Lead Manager can see.
"""

from __future__ import annotations

from typing import Any

from django.urls import reverse
from rest_framework.test import APITestCase

from leads import services
from leads.tests.factories import make_admin, make_lead, make_lead_manager, make_source, token_for


class LeadSearchTestCase(APITestCase):
    def setUp(self) -> None:
        self.admin = make_admin()
        self.source = make_source()
        self.list_url = reverse("v1:leads:lead-list")
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token_for(self.admin)}")

    def ids(self, response: Any) -> list[str]:
        return [row["id"] for row in response.data["data"]]


class TestLeadMultiFieldSearch(LeadSearchTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.target = services.create_lead(
            actor=self.admin,
            data={
                "full_name_np": "राम श्रेष्ठ",
                "full_name_en": "Ram Shrestha",
                "source": self.source,
                "email": "ram.shrestha@example.com",
            },
            contact_numbers=[{"number": "9841000111", "label": "mobile", "is_primary": True}],
        )
        self.other = make_lead(self.admin, self.source, name_np="सीता गुरुङ")

    def test_search_matches_email(self) -> None:
        resp = self.client.get(self.list_url, {"search": "ram.shrestha@example.com"})
        self.assertEqual(resp.data["meta"]["count"], 1)
        self.assertEqual(resp.data["data"][0]["id"], str(self.target.id))

    def test_search_matches_partial_contact_number(self) -> None:
        resp = self.client.get(self.list_url, {"search": "9841000"})
        self.assertEqual(resp.data["meta"]["count"], 1)
        self.assertEqual(resp.data["data"][0]["id"], str(self.target.id))

    def test_search_still_matches_devanagari_name(self) -> None:
        resp = self.client.get(self.list_url, {"search": "सीता"})
        self.assertEqual(resp.data["meta"]["count"], 1)
        self.assertEqual(resp.data["data"][0]["id"], str(self.other.id))

    def test_multiple_contact_numbers_do_not_duplicate_the_row(self) -> None:
        services.update_lead(
            actor=self.admin,
            lead=self.target,
            fields={},
            contact_numbers=[
                {"number": "9841000111", "label": "mobile", "is_primary": True},
                {"number": "9841000222", "label": "home", "is_primary": False},
            ],
        )
        resp = self.client.get(self.list_url, {"search": "984100"})
        self.assertEqual(resp.data["meta"]["count"], 1)


class TestLeadSearchRanking(LeadSearchTestCase):
    """Created oldest-exact-first, so newest-first ordering would invert this."""

    def setUp(self) -> None:
        super().setUp()
        self.exact = make_lead(self.admin, self.source, name_np="राम")
        self.prefix = make_lead(self.admin, self.source, name_np="राम बहादुर")
        self.contains = make_lead(self.admin, self.source, name_np="श्री राम श्रेष्ठ")

    def test_exact_beats_prefix_beats_contains(self) -> None:
        resp = self.client.get(self.list_url, {"search": "राम"})
        self.assertEqual(
            self.ids(resp),
            [str(self.exact.id), str(self.prefix.id), str(self.contains.id)],
        )

    def test_unsearched_list_keeps_newest_first(self) -> None:
        resp = self.client.get(self.list_url)
        self.assertEqual(
            self.ids(resp),
            [str(self.contains.id), str(self.prefix.id), str(self.exact.id)],
        )


class TestSearchRespectsOwnerScoping(LeadSearchTestCase):
    """Ranking reorders rows; it must never reveal another manager's lead."""

    def setUp(self) -> None:
        super().setUp()
        self.mine = make_lead_manager("mgr_one")
        self.theirs = make_lead_manager("mgr_two")
        self.my_lead = make_lead(self.mine, self.source, name_np="राम")
        self.their_lead = make_lead(self.theirs, self.source, name_np="राम")

    def test_lead_manager_search_returns_only_own_leads(self) -> None:
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token_for(self.mine)}")
        resp = self.client.get(self.list_url, {"search": "राम"})
        self.assertEqual(self.ids(resp), [str(self.my_lead.id)])

    def test_admin_search_returns_both(self) -> None:
        resp = self.client.get(self.list_url, {"search": "राम"})
        self.assertEqual(resp.data["meta"]["count"], 2)
