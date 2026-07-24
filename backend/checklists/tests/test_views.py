"""Endpoint tests for the checklists app.

Each endpoint is covered for success, validation failure, authentication
failure, authority failure, not-found, business-rule failure, and envelope
consistency (§18).

Two things get more attention here than the rest:

* **The authoring/tracking authority split is asserted route by route.** Four
  routes refuse a Lead Manager and fourteen admit one, and a regression in
  either direction is invisible from the outside — a Lead Manager who could edit
  a template would silently change what every future applicant for that country
  is measured against.
* **The list endpoint is asserted to be query-flat.** Progress counts are the
  reason this app has annotations at all; a serializer that quietly started
  counting items per row would still return the right numbers, and would turn
  one page into forty-one queries.
"""

from __future__ import annotations

from typing import Any

from django.db import connection
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APITestCase

from checklists.constants import ChecklistStatus, ErrorCode, ItemStatus, ItemType, TemplateStatus
from checklists.tests import factories as f

CHECKLISTS = "/api/v1/checklists/"
TEMPLATES = "/api/v1/checklists/templates/"
MISSING_ID = "2b3c4d5e-6f70-4819-a2b3-c4d5e6f70819"


class ChecklistsAPITestCase(APITestCase):
    """Shared fixtures and envelope assertions."""

    def setUp(self) -> None:
        self.admin = f.make_admin()
        self.lead_manager = f.make_lead_manager()
        self.superadmin = f.make_superadmin()
        self.catalogue = f.make_catalogue(self.admin)
        self.country = self.catalogue["country"]
        self.applicant = f.make_applicant(self.admin)
        self.journey = f.make_journey(self.admin, self.applicant)
        self.template = f.make_country_template(self.admin, self.country)

    def auth(self, user: Any) -> None:
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {f.token_for(user)}")

    def assert_success_envelope(self, response: Any) -> dict[str, Any]:
        body = response.json()
        self.assertTrue(body["success"])
        self.assertIn("data", body)
        self.assertIn("meta", body)
        return body

    def assert_error_envelope(self, response: Any, code: str) -> dict[str, Any]:
        body = response.json()
        self.assertFalse(body["success"])
        self.assertEqual(body["error"]["code"], code)
        self.assertIn("details", body["error"])
        self.assertIn("meta", body)
        return body

    def make_checklist(self) -> Any:
        from checklists import services

        return services.instantiate_checklist(journey=self.journey, template=self.template, actor=self.admin)


# ---------------------------------------------------------------------------
# Access
# ---------------------------------------------------------------------------


class AuthenticationTests(ChecklistsAPITestCase):
    def test_every_route_requires_authentication(self) -> None:
        checklist = self.make_checklist()
        item = checklist.items.first()
        routes = [
            ("get", TEMPLATES),
            ("post", TEMPLATES),
            ("get", f"{TEMPLATES}{self.template.id}/"),
            ("patch", f"{TEMPLATES}{self.template.id}/"),
            ("post", f"{TEMPLATES}{self.template.id}/items/"),
            ("get", CHECKLISTS),
            ("post", CHECKLISTS),
            ("get", f"{CHECKLISTS}{checklist.id}/"),
            ("patch", f"{CHECKLISTS}{checklist.id}/"),
            ("post", f"{CHECKLISTS}{checklist.id}/activate/"),
            ("post", f"{CHECKLISTS}{checklist.id}/complete/"),
            ("post", f"{CHECKLISTS}{checklist.id}/reopen/"),
            ("post", f"{CHECKLISTS}{checklist.id}/archive/"),
            ("post", f"{CHECKLISTS}{checklist.id}/restore/"),
            ("post", f"{CHECKLISTS}{checklist.id}/items/"),
            ("patch", f"{CHECKLISTS}{checklist.id}/items/{item.id}/"),
            ("post", f"{CHECKLISTS}{checklist.id}/items/{item.id}/status/"),
        ]
        for method, url in routes:
            with self.subTest(method=method, url=url):
                response = getattr(self.client, method)(url, {}, format="json")
                self.assertEqual(response.status_code, 401)


class AuthorityTests(ChecklistsAPITestCase):
    def test_superadmin_is_refused_everywhere(self) -> None:
        self.auth(self.superadmin)
        for method, url in (("get", TEMPLATES), ("get", CHECKLISTS), ("post", TEMPLATES)):
            with self.subTest(method=method, url=url):
                response = getattr(self.client, method)(url, {}, format="json")
                self.assertEqual(response.status_code, 403)
                self.assert_error_envelope(response, ErrorCode.ACTOR_FORBIDDEN)

    def test_lead_manager_may_read_templates_but_not_author_them(self) -> None:
        self.auth(self.lead_manager)

        self.assertEqual(self.client.get(TEMPLATES).status_code, 200)
        self.assertEqual(self.client.get(f"{TEMPLATES}{self.template.id}/").status_code, 200)

        refused = [
            ("post", TEMPLATES, {"key": "nz-student", "label": "NZ"}),
            ("patch", f"{TEMPLATES}{self.template.id}/", {"label": "Renamed"}),
            ("post", f"{TEMPLATES}{self.template.id}/items/", {"label": "Extra"}),
            (
                "patch",
                f"{TEMPLATES}{self.template.id}/items/{self.template.items.first().id}/",
                {"label": "Renamed"},
            ),
        ]
        for method, url, payload in refused:
            with self.subTest(url=url):
                response = getattr(self.client, method)(url, payload, format="json")
                self.assertEqual(response.status_code, 403)
                self.assert_error_envelope(response, ErrorCode.ACTOR_FORBIDDEN)

    def test_lead_manager_may_do_the_daily_tracking_work(self) -> None:
        """The other half of the split: collection work is not gated on an Admin."""
        checklist = self.make_checklist()
        item = checklist.items.order_by("display_order").first()
        self.auth(self.lead_manager)

        response = self.client.post(
            f"{CHECKLISTS}{checklist.id}/items/{item.id}/status/",
            {"status": ItemStatus.COMPLETED},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.assert_success_envelope(response)["data"]["status"], ItemStatus.COMPLETED)


# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------


class TemplateEndpointTests(ChecklistsAPITestCase):
    def setUp(self) -> None:
        super().setUp()
        self.auth(self.admin)

    def test_create_returns_201_and_the_template(self) -> None:
        from institutions import services as catalogue_services

        canada = catalogue_services.create_country(actor=self.admin, data={"code": "ca", "name": "Canada"})
        response = self.client.post(
            TEMPLATES,
            {
                "key": "canada-student",
                "label": "Canada — Student",
                "country": str(canada.id),
                "is_default": True,
                "status": TemplateStatus.ACTIVE,
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        data = self.assert_success_envelope(response)["data"]
        self.assertEqual(data["key"], "canada-student")
        self.assertEqual(data["country"]["name"], "Canada")
        self.assertTrue(data["is_inheritable"])

    def test_a_duplicate_key_is_a_validation_error(self) -> None:
        response = self.client.post(
            TEMPLATES,
            {"key": self.template.key, "label": "Clash"},
            format="json",
        )
        self.assertEqual(response.status_code, 400)

    def test_a_second_active_default_for_one_country_is_a_conflict(self) -> None:
        response = self.client.post(
            TEMPLATES,
            {
                "key": "australia-second",
                "label": "Australia — Second",
                "country": str(self.country.id),
                "is_default": True,
                "status": TemplateStatus.ACTIVE,
            },
            format="json",
        )
        self.assertEqual(response.status_code, 409)
        body = self.assert_error_envelope(response, ErrorCode.DEFAULT_TEMPLATE_EXISTS)
        self.assertEqual(body["error"]["details"]["existing_template_id"], str(self.template.id))

    def test_a_default_without_a_country_is_rejected(self) -> None:
        response = self.client.post(
            TEMPLATES,
            {"key": "nowhere", "label": "Nowhere", "is_default": True, "status": TemplateStatus.ACTIVE},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assert_error_envelope(response, ErrorCode.DEFAULT_REQUIRES_COUNTRY)

    def test_an_unknown_country_is_rejected(self) -> None:
        response = self.client.post(
            TEMPLATES,
            {"key": "ghost", "label": "Ghost", "country": MISSING_ID},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assert_error_envelope(response, ErrorCode.COUNTRY_NOT_FOUND)

    def test_detail_returns_the_requirements_with_the_template(self) -> None:
        response = self.client.get(f"{TEMPLATES}{self.template.id}/")
        self.assertEqual(response.status_code, 200)
        data = self.assert_success_envelope(response)["data"]
        self.assertEqual(len(data["items"]), 3)
        self.assertEqual(data["items"][0]["label"], "Passport bio page scan")

    def test_missing_template_is_404(self) -> None:
        response = self.client.get(f"{TEMPLATES}{MISSING_ID}/")
        self.assertEqual(response.status_code, 404)
        self.assert_error_envelope(response, ErrorCode.TEMPLATE_NOT_FOUND)

    def test_adding_and_retiring_a_requirement(self) -> None:
        created = self.client.post(
            f"{TEMPLATES}{self.template.id}/items/",
            {"label": "Medical certificate", "item_type": ItemType.DOCUMENT},
            format="json",
        )
        self.assertEqual(created.status_code, 201)
        item_id = self.assert_success_envelope(created)["data"]["id"]

        retired = self.client.patch(
            f"{TEMPLATES}{self.template.id}/items/{item_id}/",
            {"is_active": False},
            format="json",
        )
        self.assertEqual(retired.status_code, 200)
        self.assertFalse(self.assert_success_envelope(retired)["data"]["is_active"])

    def test_missing_requirement_is_404(self) -> None:
        response = self.client.patch(
            f"{TEMPLATES}{self.template.id}/items/{MISSING_ID}/",
            {"label": "Nope"},
            format="json",
        )
        self.assertEqual(response.status_code, 404)
        self.assert_error_envelope(response, ErrorCode.TEMPLATE_ITEM_NOT_FOUND)

    def test_country_filter(self) -> None:
        response = self.client.get(TEMPLATES, {"country": str(self.country.id)})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["data"]), 1)

    def test_an_invalid_filter_value_is_a_400_not_an_empty_page(self) -> None:
        response = self.client.get(TEMPLATES, {"status": "not-a-status"})
        self.assertEqual(response.status_code, 400)


# ---------------------------------------------------------------------------
# Checklists
# ---------------------------------------------------------------------------


class ChecklistEndpointTests(ChecklistsAPITestCase):
    def setUp(self) -> None:
        super().setUp()
        self.auth(self.admin)

    def test_applying_a_template_by_hand_returns_201_with_items_and_progress(self) -> None:
        response = self.client.post(
            CHECKLISTS,
            {"journey": str(self.journey.id), "template": str(self.template.id)},
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        data = self.assert_success_envelope(response)["data"]
        self.assertEqual(len(data["items"]), 3)
        self.assertEqual(data["origin"], "manual")
        self.assertEqual(
            data["progress"],
            {
                "total": 3,
                "resolved": 0,
                "required_total": 2,
                "required_resolved": 0,
                "blocked": 0,
                "document_total": 2,
                "document_resolved": 0,
            },
        )

    def test_applying_the_same_template_twice_is_a_conflict(self) -> None:
        payload = {"journey": str(self.journey.id), "template": str(self.template.id)}
        self.client.post(CHECKLISTS, payload, format="json")
        response = self.client.post(CHECKLISTS, payload, format="json")
        self.assertEqual(response.status_code, 409)
        self.assert_error_envelope(response, ErrorCode.TEMPLATE_ALREADY_APPLIED)

    def test_a_blank_checklist_requires_a_title(self) -> None:
        response = self.client.post(CHECKLISTS, {"journey": str(self.journey.id)}, format="json")
        self.assertEqual(response.status_code, 400)

    def test_an_unknown_journey_is_rejected(self) -> None:
        response = self.client.post(
            CHECKLISTS,
            {"journey": MISSING_ID, "title": "Orphan"},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assert_error_envelope(response, ErrorCode.JOURNEY_NOT_FOUND)

    def test_missing_checklist_is_404(self) -> None:
        response = self.client.get(f"{CHECKLISTS}{MISSING_ID}/")
        self.assertEqual(response.status_code, 404)
        self.assert_error_envelope(response, ErrorCode.CHECKLIST_NOT_FOUND)

    def test_the_applicant_filter_is_how_a_client_renders_the_applicant_panel(self) -> None:
        self.make_checklist()
        response = self.client.get(CHECKLISTS, {"applicant": str(self.applicant.id)})
        self.assertEqual(response.status_code, 200)
        rows = response.json()["data"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["applicant"]["id"], str(self.applicant.id))

    def test_completion_is_refused_and_names_the_outstanding_items(self) -> None:
        checklist = self.make_checklist()
        response = self.client.post(f"{CHECKLISTS}{checklist.id}/complete/", {}, format="json")
        self.assertEqual(response.status_code, 409)
        body = self.assert_error_envelope(response, ErrorCode.REQUIRED_ITEMS_PENDING)
        labels = {row["label"] for row in body["error"]["details"]["items"]}
        self.assertEqual(labels, {"Passport bio page scan", "Academic transcripts"})

    def test_the_full_completion_round_trip(self) -> None:
        checklist = self.make_checklist()
        for item in checklist.items.filter(is_required=True):
            response = self.client.post(
                f"{CHECKLISTS}{checklist.id}/items/{item.id}/status/",
                {"status": ItemStatus.COMPLETED},
                format="json",
            )
            self.assertEqual(response.status_code, 200)

        completed = self.client.post(f"{CHECKLISTS}{checklist.id}/complete/", {}, format="json")
        self.assertEqual(completed.status_code, 200)
        data = self.assert_success_envelope(completed)["data"]
        self.assertEqual(data["status"], ChecklistStatus.COMPLETED)
        self.assertEqual(data["progress"]["required_resolved"], 2)

        reopened = self.client.post(f"{CHECKLISTS}{checklist.id}/reopen/", {}, format="json")
        self.assertEqual(reopened.status_code, 200)
        self.assertEqual(self.assert_success_envelope(reopened)["data"]["status"], ChecklistStatus.ACTIVE)

    def test_archive_requires_a_reason_and_restore_reverses_it(self) -> None:
        checklist = self.make_checklist()

        without_reason = self.client.post(f"{CHECKLISTS}{checklist.id}/archive/", {}, format="json")
        self.assertEqual(without_reason.status_code, 400)

        archived = self.client.post(
            f"{CHECKLISTS}{checklist.id}/archive/",
            {"reason": "Applicant restarted their file."},
            format="json",
        )
        self.assertEqual(archived.status_code, 200)
        self.assertEqual(self.assert_success_envelope(archived)["data"]["status"], ChecklistStatus.ARCHIVED)

        blocked = self.client.patch(f"{CHECKLISTS}{checklist.id}/", {"title": "New"}, format="json")
        self.assertEqual(blocked.status_code, 409)
        self.assert_error_envelope(blocked, ErrorCode.CHECKLIST_ARCHIVED)

        restored = self.client.post(f"{CHECKLISTS}{checklist.id}/restore/", {}, format="json")
        self.assertEqual(restored.status_code, 200)
        self.assertEqual(self.assert_success_envelope(restored)["data"]["status"], ChecklistStatus.ACTIVE)

    def test_restore_on_a_live_checklist_is_a_conflict(self) -> None:
        checklist = self.make_checklist()
        response = self.client.post(f"{CHECKLISTS}{checklist.id}/restore/", {}, format="json")
        self.assertEqual(response.status_code, 409)
        self.assert_error_envelope(response, ErrorCode.CHECKLIST_NOT_ARCHIVED)

    def test_activating_an_already_active_checklist_is_a_conflict(self) -> None:
        checklist = self.make_checklist()
        response = self.client.post(f"{CHECKLISTS}{checklist.id}/activate/", {}, format="json")
        self.assertEqual(response.status_code, 409)
        self.assert_error_envelope(response, ErrorCode.INVALID_TRANSITION)

    def test_status_cannot_be_moved_through_the_patch_route(self) -> None:
        """A PATCH must not be able to declare a checklist complete."""
        checklist = self.make_checklist()
        response = self.client.patch(
            f"{CHECKLISTS}{checklist.id}/",
            {"status": ChecklistStatus.COMPLETED},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.assert_success_envelope(response)["data"]["status"], ChecklistStatus.ACTIVE)


class ChecklistItemEndpointTests(ChecklistsAPITestCase):
    def setUp(self) -> None:
        super().setUp()
        self.auth(self.admin)
        self.checklist = self.make_checklist()
        self.item = self.checklist.items.order_by("display_order").first()

    def test_waiving_without_a_note_is_rejected(self) -> None:
        response = self.client.post(
            f"{CHECKLISTS}{self.checklist.id}/items/{self.item.id}/status/",
            {"status": ItemStatus.WAIVED},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assert_error_envelope(response, ErrorCode.STATUS_NOTE_REQUIRED)

    def test_another_applicants_file_cannot_be_cited_as_evidence(self) -> None:
        stranger = f.make_applicant(self.admin, full_name="Someone Else")
        theirs = f.upload_for_applicant(self.admin, stranger)

        response = self.client.post(
            f"{CHECKLISTS}{self.checklist.id}/items/{self.item.id}/status/",
            {"status": ItemStatus.COMPLETED, "evidence_file": str(theirs.id)},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assert_error_envelope(response, ErrorCode.EVIDENCE_NOT_ALLOWED)

    def test_this_applicants_file_is_accepted_as_evidence(self) -> None:
        evidence = f.upload_for_applicant(self.admin, self.applicant)
        response = self.client.post(
            f"{CHECKLISTS}{self.checklist.id}/items/{self.item.id}/status/",
            {"status": ItemStatus.COMPLETED, "evidence_file": str(evidence.id)},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.assert_success_envelope(response)["data"]["evidence_file"], str(evidence.id))

    def test_an_item_id_from_another_checklist_is_404(self) -> None:
        """Item routes are scoped to their checklist — a stray id reaches nobody."""
        other_journey = f.make_journey(
            self.admin,
            f.make_applicant(self.admin, full_name="Other"),
        )
        from checklists import services

        other = services.instantiate_checklist(
            journey=other_journey,
            template=self.template,
            actor=self.admin,
        )
        stray = other.items.first()

        response = self.client.post(
            f"{CHECKLISTS}{self.checklist.id}/items/{stray.id}/status/",
            {"status": ItemStatus.COMPLETED},
            format="json",
        )
        self.assertEqual(response.status_code, 404)
        self.assert_error_envelope(response, ErrorCode.ITEM_NOT_FOUND)

    def test_an_ad_hoc_item_can_be_added_and_edited(self) -> None:
        created = self.client.post(
            f"{CHECKLISTS}{self.checklist.id}/items/",
            {"label": "Extra reference letter", "is_required": False},
            format="json",
        )
        self.assertEqual(created.status_code, 201)
        item_id = self.assert_success_envelope(created)["data"]["id"]

        updated = self.client.patch(
            f"{CHECKLISTS}{self.checklist.id}/items/{item_id}/",
            {"label": "Extra reference letter (signed)"},
            format="json",
        )
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(
            self.assert_success_envelope(updated)["data"]["label"],
            "Extra reference letter (signed)",
        )


# ---------------------------------------------------------------------------
# The safety net, and the query budget
# ---------------------------------------------------------------------------


class SafetyNetTests(ChecklistsAPITestCase):
    def test_a_journey_whose_country_has_no_template_is_listed(self) -> None:
        from institutions import services as catalogue_services

        nowhere = catalogue_services.create_country(
            actor=self.admin,
            data={"code": "nz", "name": "New Zealand"},
        )
        with self.captureOnCommitCallbacks(execute=True):
            stranded = f.make_journey(
                self.admin,
                f.make_applicant(self.admin, full_name="Gita"),
                target_country_ref=nowhere,
            )

        self.auth(self.admin)
        response = self.client.get(CHECKLISTS, {"journey_missing_checklist": "true"})
        self.assertEqual(response.status_code, 200)
        ids = {row["id"] for row in response.json()["data"]}
        self.assertIn(str(stranded.id), ids)

    def test_a_journey_that_did_inherit_is_not_listed(self) -> None:
        with self.captureOnCommitCallbacks(execute=True):
            self.journey.target_country_ref = self.country
            self.journey.save()

        self.auth(self.admin)
        response = self.client.get(CHECKLISTS, {"journey_missing_checklist": "true"})
        ids = {row["id"] for row in response.json()["data"]}
        self.assertNotIn(str(self.journey.id), ids)


class QueryBudgetTests(ChecklistsAPITestCase):
    def test_the_list_endpoint_does_not_scale_queries_with_row_count(self) -> None:
        """Progress counts come from annotations, and this is what proves it."""
        from checklists import services

        for index in range(4):
            journey = f.make_journey(
                self.admin,
                f.make_applicant(self.admin, full_name=f"Person {index}"),
            )
            services.instantiate_checklist(journey=journey, template=self.template, actor=self.admin)

        self.auth(self.admin)
        with CaptureQueriesContext(connection) as ctx:
            response = self.client.get(CHECKLISTS)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["data"]), 4)
        # Auth, count, page — a per-row count would push this well past ten.
        self.assertLess(len(ctx.captured_queries), 10)
