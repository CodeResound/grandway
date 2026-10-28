"""Optional applicant assignment — POST /applicants/<id>/assign/ and ?assigned_to= (2026-10-29).

Assignment routes notifications only. These pin who may set it, that it never
narrows what anyone can read, the list filter, and conversion handing the
applicant to the lead's owner.
"""

from __future__ import annotations

from typing import Any

from audit.models import AuditEvent
from django.urls import reverse
from leads import services as lead_services
from leads.tests.factories import make_lead, make_source
from rest_framework.test import APITestCase

from applicants import services
from applicants.constants import ApplicantAuditAction, ApplicantStatus, ErrorCode
from applicants.tests.factories import make_admin, make_applicant, make_lead_manager, make_superadmin, token_for


class AssignApiTests(APITestCase):
    def setUp(self) -> None:
        self.admin = make_admin()
        self.manager = make_lead_manager()
        self.other_manager = make_lead_manager("othermgr")
        self.applicant = make_applicant(self.admin)
        self.url = reverse("v1:applicants:applicant-assign", args=[self.applicant.id])

    def assign(self, user: Any, assigned_to: Any) -> Any:
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token_for(user)}")
        value = str(assigned_to.id) if hasattr(assigned_to, "id") else assigned_to
        return self.client.post(self.url, {"assigned_to": value}, format="json")

    def holder(self) -> Any:
        self.applicant.refresh_from_db()
        return self.applicant.assigned_to

    def test_admin_assigns_anyone_and_clears(self) -> None:
        response = self.assign(self.admin, self.manager)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["data"]["assigned_to"]["id"], str(self.manager.id))
        self.assertEqual(self.assign(self.admin, self.other_manager).status_code, 200)
        self.assertEqual(self.holder(), self.other_manager)
        self.assertEqual(self.assign(self.admin, None).status_code, 200)
        self.assertIsNone(self.holder())

    def test_lead_manager_takes_and_releases_only(self) -> None:
        self.assertEqual(self.assign(self.manager, self.manager).status_code, 200)
        # Someone else cannot take it, or hand it on, or clear it.
        for user, target in ((self.other_manager, self.other_manager), (self.other_manager, None)):
            response = self.assign(user, target)
            self.assertEqual(response.status_code, 403)
            self.assertEqual(response.json()["error"]["code"], ErrorCode.ASSIGNMENT_FORBIDDEN)
        self.assertEqual(self.assign(self.manager, self.other_manager).status_code, 403)
        self.assertEqual(self.assign(self.manager, None).status_code, 200)
        self.assertIsNone(self.holder())

    def test_lead_manager_cannot_assign_someone_else_to_an_unassigned_applicant(self) -> None:
        self.assertEqual(self.assign(self.manager, self.other_manager).status_code, 403)

    def test_invalid_assignees(self) -> None:
        blocked = make_lead_manager("blocked")
        blocked.is_active = False
        blocked.save(update_fields=["is_active"])
        for target in (make_superadmin(), blocked, "7c8d9e0f-1a2b-3c4d-5e6f-708192a3b4c5"):
            with self.subTest(target=target):
                response = self.assign(self.admin, target)
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.json()["error"]["code"], ErrorCode.ASSIGNEE_INVALID)

    def test_missing_key_is_a_validation_error(self) -> None:
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token_for(self.admin)}")
        self.assertEqual(self.client.post(self.url, {}, format="json").json()["error"]["code"], "VALIDATION_ERROR")

    def test_superadmin_and_archived(self) -> None:
        self.assertEqual(self.assign(make_superadmin("root2"), self.manager).status_code, 403)
        services.change_status(actor=self.admin, applicant=self.applicant, status=ApplicantStatus.ARCHIVED)
        response = self.assign(self.admin, self.manager)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["error"]["code"], ErrorCode.APPLICANT_ARCHIVED)

    def test_audit_and_no_op(self) -> None:
        self.assign(self.admin, self.manager)
        self.assign(self.admin, self.manager)  # no-op
        self.assign(self.admin, None)
        actions = list(
            AuditEvent.objects.filter(entity_id=str(self.applicant.id))
            .filter(action__in=[ApplicantAuditAction.APPLICANT_ASSIGNED, ApplicantAuditAction.APPLICANT_UNASSIGNED])
            .order_by("created_at")
            .values_list("action", flat=True)
        )
        self.assertEqual(actions, [ApplicantAuditAction.APPLICANT_ASSIGNED, ApplicantAuditAction.APPLICANT_UNASSIGNED])

    def test_assignment_never_narrows_access(self) -> None:
        self.assign(self.admin, self.manager)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token_for(self.other_manager)}")
        detail = reverse("v1:applicants:applicant-detail", args=[self.applicant.id])
        self.assertEqual(self.client.get(detail).status_code, 200)
        self.assertEqual(self.client.patch(detail, {"nationality": "Nepali"}, format="json").status_code, 200)


class AssignedToFilterTests(APITestCase):
    def setUp(self) -> None:
        self.admin = make_admin()
        self.manager = make_lead_manager()
        self.mine = make_applicant(self.admin, name="Mine")
        self.theirs = make_applicant(self.admin, name="Theirs")
        self.nobody = make_applicant(self.admin, name="Nobody")
        services.assign_applicant(actor=self.admin, applicant=self.mine, assignee=self.manager)
        services.assign_applicant(actor=self.admin, applicant=self.theirs, assignee=self.admin)

    def names(self, user: Any, value: str) -> list[str]:
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token_for(user)}")
        response = self.client.get(reverse("v1:applicants:applicant-list"), {"assigned_to": value})
        self.assertEqual(response.status_code, 200, response.content)
        return sorted(row["full_name"] for row in response.json()["data"])

    def test_me_none_and_id(self) -> None:
        self.assertEqual(self.names(self.manager, "me"), ["Mine"])
        self.assertEqual(self.names(self.manager, "none"), ["Nobody"])
        self.assertEqual(self.names(self.manager, str(self.admin.id)), ["Theirs"])

    def test_list_rows_carry_the_assignee(self) -> None:
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token_for(self.admin)}")
        rows = {r["full_name"]: r for r in self.client.get(reverse("v1:applicants:applicant-list")).json()["data"]}
        self.assertEqual(rows["Mine"]["assigned_to"]["username"], self.manager.username)
        self.assertIsNone(rows["Nobody"]["assigned_to"])

    def test_garbage_is_a_400(self) -> None:
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token_for(self.admin)}")
        response = self.client.get(reverse("v1:applicants:applicant-list"), {"assigned_to": "someone"})
        self.assertEqual(response.status_code, 400)


class ConversionAssignsTheLeadOwnerTests(APITestCase):
    def setUp(self) -> None:
        self.admin = make_admin()
        self.owner = make_lead_manager("owner")
        self.lead = make_lead(self.owner, make_source())

    def convert(self) -> Any:
        lead_services.convert_lead(actor=self.admin, lead=self.lead)
        self.lead.refresh_from_db()
        return self.lead.converted_applicant

    def test_owner_becomes_assignee(self) -> None:
        self.assertEqual(self.convert().assigned_to, self.owner)

    def test_inactive_owner_leaves_it_unassigned(self) -> None:
        self.owner.is_active = False
        self.owner.save(update_fields=["is_active"])
        self.assertIsNone(self.convert().assigned_to)
