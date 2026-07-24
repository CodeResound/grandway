"""Catalogue endpoints: access split, CRUD, search filters, envelopes, and N+1."""

from __future__ import annotations

from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from institutions import services
from institutions.constants import AvailabilityStatus, ErrorCode
from institutions.tests.factories import (
    make_admin,
    make_campus,
    make_country,
    make_field,
    make_institution,
    make_lead_manager,
    make_program,
    make_superadmin,
    priced,
    token_for,
)

MISSING_UUID = "00000000-0000-0000-0000-000000000000"


class CatalogueApiTestCase(APITestCase):
    def setUp(self) -> None:
        self.admin = make_admin()
        self.manager = make_lead_manager()
        self.superadmin = make_superadmin()

        self.field = make_field(self.admin)
        self.country = make_country(self.admin)
        self.institution = make_institution(self.admin, self.country)

    def auth(self, user: object) -> None:
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token_for(user)}")

    # -- URL helpers --------------------------------------------------------

    @property
    def fields_url(self) -> str:
        return reverse("v1:catalogue:field-list")

    @property
    def countries_url(self) -> str:
        return reverse("v1:catalogue:country-list")

    @property
    def institutions_url(self) -> str:
        return reverse("v1:catalogue:institution-list")

    @property
    def programs_url(self) -> str:
        return reverse("v1:catalogue:program-list")

    def campuses_url(self, institution: object) -> str:
        return reverse("v1:catalogue:campus-list", args=[institution.id])


class TestAccessSplit(CatalogueApiTestCase):
    """The app's defining shape: everyone reads, only Admin writes."""

    def test_unauthenticated_read_is_401(self) -> None:
        self.assertEqual(self.client.get(self.programs_url).status_code, status.HTTP_401_UNAUTHORIZED)

    def test_unauthenticated_write_is_401(self) -> None:
        resp = self.client.post(self.countries_url, {"code": "ca", "name": "Canada"}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_lead_manager_may_read(self) -> None:
        """Search is the point of the catalogue; a manager who cannot see it cannot counsel."""
        self.auth(self.manager)
        self.assertEqual(self.client.get(self.programs_url).status_code, status.HTTP_200_OK)

    def test_lead_manager_may_not_create(self) -> None:
        self.auth(self.manager)
        resp = self.client.post(self.countries_url, {"code": "ca", "name": "Canada"}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(resp.data["error"]["code"], ErrorCode.ACTOR_FORBIDDEN)

    def test_lead_manager_may_not_update(self) -> None:
        self.auth(self.manager)
        url = reverse("v1:catalogue:country-detail", args=[self.country.id])
        resp = self.client.patch(url, {"notes": "edited"}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_superadmin_may_not_even_read(self) -> None:
        """A platform authority does not participate in consultancy operations."""
        self.auth(self.superadmin)
        resp = self.client.get(self.programs_url)
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(resp.data["error"]["code"], ErrorCode.ACTOR_FORBIDDEN)

    def test_admin_may_write(self) -> None:
        self.auth(self.admin)
        resp = self.client.post(self.countries_url, {"code": "ca", "name": "Canada"}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)


class TestEnvelopes(CatalogueApiTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.auth(self.admin)

    def test_success_envelope_shape(self) -> None:
        resp = self.client.get(self.countries_url)
        self.assertTrue(resp.data["success"])
        self.assertIn("data", resp.data)
        self.assertIn("meta", resp.data)
        self.assertEqual(
            set(resp.data["meta"]),
            {"count", "page", "page_size", "next", "previous"},
        )

    def test_error_envelope_shape(self) -> None:
        resp = self.client.get(reverse("v1:catalogue:country-detail", args=[MISSING_UUID]))
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)
        self.assertFalse(resp.data["success"])
        self.assertEqual(set(resp.data["error"]), {"code", "message", "details"})
        self.assertEqual(resp.data["error"]["code"], ErrorCode.COUNTRY_NOT_FOUND)

    def test_every_resource_returns_its_own_not_found_code(self) -> None:
        cases = [
            ("v1:catalogue:field-detail", ErrorCode.FIELD_NOT_FOUND),
            ("v1:catalogue:country-detail", ErrorCode.COUNTRY_NOT_FOUND),
            ("v1:catalogue:institution-detail", ErrorCode.INSTITUTION_NOT_FOUND),
            ("v1:catalogue:campus-detail", ErrorCode.CAMPUS_NOT_FOUND),
            ("v1:catalogue:program-detail", ErrorCode.PROGRAM_NOT_FOUND),
        ]
        for route, expected in cases:
            with self.subTest(route=route):
                resp = self.client.get(reverse(route, args=[MISSING_UUID]))
                self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)
                self.assertEqual(resp.data["error"]["code"], expected)


class TestFieldEndpoints(CatalogueApiTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.auth(self.admin)

    def test_create_and_list(self) -> None:
        resp = self.client.post(self.fields_url, {"code": "nursing", "name": "Nursing"}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(resp.data["data"]["code"], "nursing")

        listing = self.client.get(self.fields_url)
        self.assertEqual(listing.data["meta"]["count"], 2)

    def test_duplicate_code_is_409(self) -> None:
        resp = self.client.post(
            self.fields_url,
            {"code": self.field.code, "name": "Duplicate"},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(resp.data["error"]["code"], ErrorCode.CODE_DUPLICATE)

    def test_devanagari_code_is_rejected(self) -> None:
        """Codes are ASCII system identifiers (§39.7)."""
        resp = self.client.post(self.fields_url, {"code": "सूचना", "name": "IT"}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_code_is_immutable(self) -> None:
        url = reverse("v1:catalogue:field-detail", args=[self.field.id])
        resp = self.client.patch(url, {"code": "changed", "name": "Renamed"}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["data"]["code"], self.field.code)
        self.assertEqual(resp.data["data"]["name"], "Renamed")

    def test_filter_by_active(self) -> None:
        make_field(self.admin, code="dormant", name="Dormant", is_active=False)
        resp = self.client.get(self.fields_url, {"is_active": "true"})
        self.assertEqual(resp.data["meta"]["count"], 1)


class TestCountryEndpoints(CatalogueApiTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.auth(self.admin)
        self.detail_url = reverse("v1:catalogue:country-detail", args=[self.country.id])

    def test_pausing_without_a_note_is_400(self) -> None:
        resp = self.client.patch(
            self.detail_url,
            {"availability_status": AvailabilityStatus.PAUSED},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(resp.data["error"]["code"], ErrorCode.AVAILABILITY_NOTE_REQUIRED)

    def test_pausing_with_a_note_succeeds(self) -> None:
        resp = self.client.patch(
            self.detail_url,
            {
                "availability_status": AvailabilityStatus.PAUSED,
                "availability_note": "Partner agreement under review.",
            },
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["data"]["availability_status"], AvailabilityStatus.PAUSED)
        self.assertFalse(resp.data["data"]["is_usable"])

    def test_duplicate_code_is_409(self) -> None:
        resp = self.client.post(
            self.countries_url,
            {"code": self.country.code, "name": "Duplicate"},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(resp.data["error"]["code"], ErrorCode.CODE_DUPLICATE)

    def test_english_name_is_required(self) -> None:
        resp = self.client.post(self.countries_url, {"code": "kr"}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)


class TestCampusEndpoints(CatalogueApiTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.auth(self.admin)

    def test_create_under_institution(self) -> None:
        resp = self.client.post(
            self.campuses_url(self.institution),
            {"name": "Parkville", "city": "Melbourne"},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(resp.data["data"]["institution"]["id"], str(self.institution.id))

    def test_duplicate_name_within_institution_is_409(self) -> None:
        make_campus(self.admin, self.institution, name="Parkville")
        resp = self.client.post(
            self.campuses_url(self.institution),
            {"name": "Parkville"},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(resp.data["error"]["code"], ErrorCode.CAMPUS_DUPLICATE)

    def test_same_name_under_a_different_institution_is_fine(self) -> None:
        make_campus(self.admin, self.institution, name="City")
        other = make_institution(self.admin, self.country, name="RMIT University")
        resp = self.client.post(self.campuses_url(other), {"name": "City"}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)

    def test_create_under_missing_institution_is_404(self) -> None:
        resp = self.client.post(
            reverse("v1:catalogue:campus-list", args=[MISSING_UUID]),
            {"name": "Ghost"},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(resp.data["error"]["code"], ErrorCode.INSTITUTION_NOT_FOUND)

    def test_list_is_scoped_to_the_institution(self) -> None:
        make_campus(self.admin, self.institution, name="Parkville")
        other = make_institution(self.admin, self.country, name="Deakin University")
        make_campus(self.admin, other, name="Burwood")

        resp = self.client.get(self.campuses_url(self.institution))
        self.assertEqual(resp.data["meta"]["count"], 1)
        self.assertEqual(resp.data["data"][0]["name"], "Parkville")


class TestProgramWrites(CatalogueApiTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.auth(self.admin)

    def _payload(self, **overrides: object) -> dict:
        payload = {
            "institution": str(self.institution.id),
            "field": str(self.field.id),
            "title": "Master of Information Technology",
            "qualification_level": "masters",
        }
        payload.update(overrides)
        return payload

    def test_minimal_create(self) -> None:
        """Only institution, title, level, and field are required."""
        resp = self.client.post(self.programs_url, self._payload(), format="json")
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertIsNone(resp.data["data"]["tuition_amount"])

    def test_missing_qualification_level_is_400(self) -> None:
        payload = self._payload()
        del payload["qualification_level"]
        resp = self.client.post(self.programs_url, payload, format="json")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_invalid_qualification_level_is_400(self) -> None:
        resp = self.client.post(self.programs_url, self._payload(qualification_level="wizardry"), format="json")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_tuition_amount_without_currency_is_400(self) -> None:
        resp = self.client.post(
            self.programs_url,
            self._payload(tuition_amount="49824.00", tuition_fee_period="total_program"),
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(resp.data["error"]["code"], ErrorCode.TUITION_INCOMPLETE)

    def test_negative_tuition_is_400(self) -> None:
        resp = self.client.post(
            self.programs_url,
            self._payload(tuition_amount="-1.00", tuition_currency="AUD", tuition_fee_period="per_year"),
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_currency_is_upper_cased(self) -> None:
        resp = self.client.post(
            self.programs_url,
            self._payload(tuition_amount="1000.00", tuition_currency="aud", tuition_fee_period="per_year"),
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(resp.data["data"]["tuition_currency"], "AUD")

    def test_campus_of_another_institution_is_400(self) -> None:
        other = make_institution(self.admin, self.country, name="Monash University")
        foreign_campus = make_campus(self.admin, other, name="Clayton")
        resp = self.client.post(
            self.programs_url,
            self._payload(campus=str(foreign_campus.id)),
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(resp.data["error"]["code"], ErrorCode.CAMPUS_INSTITUTION_MISMATCH)

    def test_institution_is_immutable(self) -> None:
        program = make_program(self.admin, self.institution, self.field)
        other = make_institution(self.admin, self.country, name="Griffith University")
        url = reverse("v1:catalogue:program-detail", args=[program.id])

        resp = self.client.patch(url, {"institution": str(other.id)}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["data"]["institution"]["id"], str(self.institution.id))

    def test_detail_carries_entry_expectations_and_list_does_not(self) -> None:
        make_program(
            self.admin,
            self.institution,
            self.field,
            academic_requirement="Bachelor's, 65%.",
        )
        listing = self.client.get(self.programs_url)
        self.assertNotIn("academic_requirement", listing.data["data"][0])

        detail = self.client.get(
            reverse("v1:catalogue:program-detail", args=[listing.data["data"][0]["id"]]),
        )
        self.assertEqual(detail.data["data"]["academic_requirement"], "Bachelor's, 65%.")


class TestProgramSearch(CatalogueApiTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.auth(self.manager)

        self.nursing = make_field(self.admin, code="nursing", name="Nursing")
        self.active = make_program(self.admin, self.institution, self.field, **priced("40000.00"))
        self.paused = make_program(
            self.admin,
            self.institution,
            self.field,
            title="Master of Data Science",
            availability_status=AvailabilityStatus.PAUSED,
            availability_note="Intake suspended.",
        )
        self.inactive = make_program(
            self.admin,
            self.institution,
            self.nursing,
            title="Bachelor of Nursing",
            qualification_level="bachelors",
            availability_status=AvailabilityStatus.INACTIVE,
            availability_note="Withdrawn 2026.",
        )

    def test_default_excludes_paused_and_inactive(self) -> None:
        """The concept requires that inactive items are hidden from active selection."""
        resp = self.client.get(self.programs_url)
        titles = [row["title"] for row in resp.data["data"]]
        self.assertEqual(titles, [self.active.title])

    def test_usable_only_false_returns_everything(self) -> None:
        resp = self.client.get(self.programs_url, {"usable_only": "false"})
        self.assertEqual(resp.data["meta"]["count"], 3)

    def test_explicit_status_filter_overrides_the_default(self) -> None:
        resp = self.client.get(self.programs_url, {"availability_status": AvailabilityStatus.INACTIVE})
        self.assertEqual(resp.data["meta"]["count"], 1)
        self.assertEqual(resp.data["data"][0]["title"], "Bachelor of Nursing")

    def test_is_usable_is_per_record_not_per_chain(self) -> None:
        """The one place `is_usable` and search results deliberately disagree.

        `is_usable` reflects only the record it sits on. A program under a
        paused country still reports true while being excluded from search.
        Documented in INTEGRATION.md §4; asserted here so it cannot drift into
        a chain-aware property without someone deciding to.
        """
        services.update_country(
            actor=self.admin,
            country=self.country,
            fields={
                "availability_status": AvailabilityStatus.PAUSED,
                "availability_note": "Agreement lapsed.",
            },
        )
        detail = self.client.get(reverse("v1:catalogue:program-detail", args=[self.active.id]))
        self.assertTrue(detail.data["data"]["is_usable"])
        self.assertEqual(detail.data["data"]["country"]["availability_status"], AvailabilityStatus.PAUSED)

        # ...yet the same program is absent from the default search.
        self.assertEqual(self.client.get(self.programs_url).data["meta"]["count"], 0)

    def test_inactive_field_does_not_withdraw_its_programs(self) -> None:
        """`Field.is_active` is deliberately outside the usability chain."""
        services.update_field(actor=self.admin, field=self.field, fields={"is_active": False})
        resp = self.client.get(self.programs_url)
        self.assertEqual(resp.data["meta"]["count"], 1)

    def test_a_program_at_a_paused_institution_is_not_usable(self) -> None:
        """Availability composes across the chain even though it never cascades on write."""
        services.update_institution(
            actor=self.admin,
            institution=self.institution,
            fields={
                "availability_status": AvailabilityStatus.PAUSED,
                "availability_note": "Agreement lapsed.",
            },
        )
        resp = self.client.get(self.programs_url)
        self.assertEqual(resp.data["meta"]["count"], 0)

    def test_filter_by_level(self) -> None:
        resp = self.client.get(self.programs_url, {"qualification_level": "bachelors", "usable_only": "false"})
        self.assertEqual(resp.data["meta"]["count"], 1)

    def test_filter_by_field(self) -> None:
        resp = self.client.get(self.programs_url, {"field": str(self.nursing.id), "usable_only": "false"})
        self.assertEqual(resp.data["meta"]["count"], 1)

    def test_filter_by_country(self) -> None:
        resp = self.client.get(self.programs_url, {"country": str(self.country.id), "usable_only": "false"})
        self.assertEqual(resp.data["meta"]["count"], 3)

    def test_tuition_ceiling_excludes_unpriced_programs(self) -> None:
        """An unknown fee is not a cheap one."""
        resp = self.client.get(self.programs_url, {"tuition_max": "50000.00", "usable_only": "false"})
        self.assertEqual(resp.data["meta"]["count"], 1)
        self.assertEqual(resp.data["data"][0]["id"], str(self.active.id))

    def test_tuition_ceiling_below_the_price_returns_nothing(self) -> None:
        resp = self.client.get(self.programs_url, {"tuition_max": "1000.00", "usable_only": "false"})
        self.assertEqual(resp.data["meta"]["count"], 0)

    def test_text_search_matches_program_title(self) -> None:
        resp = self.client.get(self.programs_url, {"q": "Data Science", "usable_only": "false"})
        self.assertEqual(resp.data["meta"]["count"], 1)

    def test_text_search_matches_institution_name(self) -> None:
        resp = self.client.get(self.programs_url, {"q": "Melbourne", "usable_only": "false"})
        self.assertEqual(resp.data["meta"]["count"], 3)

    def test_unparseable_filter_is_rejected_not_ignored(self) -> None:
        """Silently ignoring it would return the whole catalogue as if it were a result."""
        resp = self.client.get(self.programs_url, {"tuition_max": "cheap"})
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_invalid_level_filter_is_rejected(self) -> None:
        resp = self.client.get(self.programs_url, {"qualification_level": "wizardry"})
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)


class TestProgramListQueryCount(CatalogueApiTestCase):
    """The program list must not scale its query count with the number of rows."""

    def _make_programs(self, count: int, offset: int = 0) -> None:
        campus = make_campus(self.admin, self.institution, name=f"Campus {offset}")
        for index in range(count):
            make_program(
                self.admin,
                self.institution,
                self.field,
                title=f"Program {offset + index}",
                campus=campus,
                **priced(),
            )

    def test_query_count_does_not_grow_with_row_count(self) -> None:
        """Asserted as a comparison, not a constant.

        A fixed number would pin this test to the authentication layer's query
        count, which has nothing to do with the selector under test. Equality
        across a fivefold increase in rows is what "no N+1" actually claims.
        """
        self.auth(self.manager)
        self._make_programs(2)

        with CaptureQueriesContext(connection) as few:
            first = self.client.get(self.programs_url)
        self.assertEqual(first.data["meta"]["count"], 2)

        self._make_programs(8, offset=2)

        with CaptureQueriesContext(connection) as many:
            second = self.client.get(self.programs_url)
        self.assertEqual(second.data["meta"]["count"], 10)

        self.assertEqual(len(many), len(few))

    def test_list_row_carries_its_joined_relations(self) -> None:
        """The joins exist to be displayed — if a row cannot name its provider,
        country, campus, and field, the select_related is pointless."""
        self.auth(self.manager)
        self._make_programs(1)

        row = self.client.get(self.programs_url).data["data"][0]
        self.assertEqual(row["institution"]["name"], self.institution.name)
        self.assertEqual(row["country"]["name"], self.country.name)
        self.assertEqual(row["field"]["code"], self.field.code)
        self.assertEqual(row["campus"]["name"], "Campus 0")
        # DecimalField renders as a string, so money never passes through a float.
        self.assertEqual(row["tuition_amount"], "49824.00")
