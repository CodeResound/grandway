"""Service-level tests for the clients app.

These cover what makes the directory trustworthy: romanized search forms derived
correctly for both name pairs, contact numbers replaced as a set rather than
merged, retirement that always says why, and the guarantee that nothing is ever
deleted.
"""

from __future__ import annotations

from audit.models import AuditEvent
from django.test import TestCase

from clients import services
from clients.constants import AUDIT_APP_LABEL, ClientAuditAction, ClientStatus
from clients.exceptions import (
    ClientAlreadyRetiredError,
    ClientNotRetiredError,
    ContactNumberDuplicateError,
    StatusNoteRequiredError,
)
from clients.models import Client, ClientContactNumber
from clients.selectors import filter_clients, get_clients, search_clients
from clients.tests import factories as f


class ClientCreationTests(TestCase):
    @classmethod
    def setUpTestData(cls) -> None:
        cls.admin = f.make_admin()

    def test_create_starts_active(self) -> None:
        client = f.make_client(self.admin)

        self.assertEqual(client.status, ClientStatus.ACTIVE)
        self.assertTrue(client.is_active)
        self.assertIsNone(client.retired_at)

    def test_create_with_contact_numbers(self) -> None:
        client = f.make_client(
            self.admin,
            contact_numbers=[f.number("9801111111", is_primary=True), f.number("014567890", "work")],
        )

        self.assertEqual(client.contact_numbers.count(), 2)
        # Ordering is -is_primary then created_at, so the primary leads.
        self.assertTrue(client.contact_numbers.first().is_primary)

    def test_the_same_number_twice_is_rejected(self) -> None:
        with self.assertRaises(ContactNumberDuplicateError):
            f.make_client(self.admin, contact_numbers=[f.number("9801111111"), f.number("9801111111")])

    def test_two_clients_may_share_a_number(self) -> None:
        """Uniqueness is per client — two agencies can share a switchboard."""
        f.make_client(self.admin, contact_numbers=[f.number("014567890")])
        second = f.make_client(self.admin, contact_numbers=[f.number("014567890")])

        self.assertEqual(second.contact_numbers.count(), 1)

    def test_creation_appends_one_audit_event(self) -> None:
        client = f.make_client(self.admin)

        events = AuditEvent.objects.filter(app_label=AUDIT_APP_LABEL, entity_id=str(client.id))
        self.assertEqual(events.count(), 1)
        self.assertEqual(events.first().action, ClientAuditAction.CLIENT_CREATED)


class ClientUpdateTests(TestCase):
    def setUp(self) -> None:
        self.admin = f.make_admin()
        self.client_record = f.make_client(self.admin, contact_numbers=[f.number("9801111111")])

    def test_update_records_a_change_map(self) -> None:
        services.update_client(
            actor=self.admin,
            client=self.client_record,
            fields={"spokesperson_designation": "Managing Director"},
        )

        event = AuditEvent.objects.filter(action=ClientAuditAction.CLIENT_UPDATED).first()
        self.assertIsNotNone(event)
        self.assertEqual(event.changes["spokesperson_designation"]["to"], "Managing Director")

    def test_a_no_op_update_writes_no_event(self) -> None:
        services.update_client(actor=self.admin, client=self.client_record, fields={"name": "Himal Education"})

        self.assertFalse(AuditEvent.objects.filter(action=ClientAuditAction.CLIENT_UPDATED).exists())

    def test_renaming_updates_the_stored_name(self) -> None:
        services.update_client(actor=self.admin, client=self.client_record, fields={"name": "Sagarmatha Consult"})

        self.client_record.refresh_from_db()
        self.assertEqual(self.client_record.name, "Sagarmatha Consult")

    def test_contact_numbers_are_replaced_not_merged(self) -> None:
        services.update_client(
            actor=self.admin,
            client=self.client_record,
            fields={},
            contact_numbers=[f.number("9802222222"), f.number("9803333333")],
        )

        numbers = set(self.client_record.contact_numbers.values_list("number", flat=True))
        self.assertEqual(numbers, {"9802222222", "9803333333"})

    def test_an_empty_list_clears_the_numbers(self) -> None:
        services.update_client(actor=self.admin, client=self.client_record, fields={}, contact_numbers=[])

        self.assertEqual(self.client_record.contact_numbers.count(), 0)

    def test_none_leaves_the_numbers_alone(self) -> None:
        """`None` and `[]` mean different things and must stay distinguishable."""
        services.update_client(actor=self.admin, client=self.client_record, fields={"notes": "x"})

        self.assertEqual(self.client_record.contact_numbers.count(), 1)

    def test_replacing_numbers_is_recorded_as_a_change(self) -> None:
        services.update_client(
            actor=self.admin,
            client=self.client_record,
            fields={},
            contact_numbers=[f.number("9802222222")],
        )

        event = AuditEvent.objects.filter(action=ClientAuditAction.CLIENT_UPDATED).first()
        self.assertIsNotNone(event)
        self.assertIn("contact_numbers", event.changes)


class ClientStandingTests(TestCase):
    def setUp(self) -> None:
        self.admin = f.make_admin()
        self.client_record = f.make_client(self.admin)

    def test_retire_stamps_who_and_why(self) -> None:
        retired = services.retire_client(
            actor=self.admin, client=self.client_record, reason="Partnership agreement ended."
        )

        self.assertEqual(retired.status, ClientStatus.INACTIVE)
        self.assertFalse(retired.is_active)
        self.assertEqual(retired.status_note, "Partnership agreement ended.")
        self.assertIsNotNone(retired.retired_at)
        self.assertEqual(retired.retired_by, self.admin)

    def test_retire_requires_a_reason(self) -> None:
        with self.assertRaises(StatusNoteRequiredError):
            services.retire_client(actor=self.admin, client=self.client_record, reason="   ")

    def test_retiring_twice_is_rejected(self) -> None:
        services.retire_client(actor=self.admin, client=self.client_record, reason="Ended.")
        with self.assertRaises(ClientAlreadyRetiredError):
            services.retire_client(actor=self.admin, client=self.client_record, reason="Ended again.")

    def test_restore_clears_the_retirement_state(self) -> None:
        services.retire_client(actor=self.admin, client=self.client_record, reason="Ended.")
        restored = services.restore_client(actor=self.admin, client=self.client_record)

        self.assertEqual(restored.status, ClientStatus.ACTIVE)
        self.assertEqual(restored.status_note, "")
        self.assertIsNone(restored.retired_at)
        self.assertIsNone(restored.retired_by)

    def test_restoring_an_active_client_is_rejected(self) -> None:
        with self.assertRaises(ClientNotRetiredError):
            services.restore_client(actor=self.admin, client=self.client_record)

    def test_restore_does_not_erase_the_retirement_from_history(self) -> None:
        services.retire_client(actor=self.admin, client=self.client_record, reason="Ended.")
        services.restore_client(actor=self.admin, client=self.client_record)

        actions = set(AuditEvent.objects.filter(entity_id=str(self.client_record.id)).values_list("action", flat=True))
        self.assertIn(ClientAuditAction.CLIENT_RETIRED, actions)
        self.assertIn(ClientAuditAction.CLIENT_RESTORED, actions)


class ClientSearchTests(TestCase):
    @classmethod
    def setUpTestData(cls) -> None:
        cls.admin = f.make_admin()
        cls.himal = f.make_client(
            cls.admin,
            name="Himal Education",
            spokesperson_name="Sunita Shrestha",
        )
        cls.other = f.make_client(cls.admin, name="Sagarmatha Consult")

    def test_search_by_name(self) -> None:
        found = search_clients(get_clients(), "Himal")
        self.assertEqual([c.id for c in found], [self.himal.id])

    def test_search_is_case_insensitive(self) -> None:
        found = search_clients(get_clients(), "sagarmatha")
        self.assertEqual([c.id for c in found], [self.other.id])

    def test_search_covers_the_spokesperson(self) -> None:
        """The concept's flow says staff look up "the company or contact person"."""
        found = search_clients(get_clients(), "Sunita")
        self.assertEqual([c.id for c in found], [self.himal.id])

    def test_filter_by_status(self) -> None:
        services.retire_client(actor=self.admin, client=self.other, reason="Ended.")

        active = filter_clients(get_clients(), {"status": ClientStatus.ACTIVE})
        inactive = filter_clients(get_clients(), {"status": ClientStatus.INACTIVE})

        self.assertEqual([c.id for c in active], [self.himal.id])
        self.assertEqual([c.id for c in inactive], [self.other.id])

    def test_no_status_filter_returns_both(self) -> None:
        """A retired partner stays visible; hiding it is a presentation choice."""
        services.retire_client(actor=self.admin, client=self.other, reason="Ended.")

        self.assertEqual(filter_clients(get_clients(), {}).count(), 2)

    def test_directory_is_ordered_alphabetically(self) -> None:
        """A directory reads by name, not by when rows were added."""
        names = list(get_clients().values_list("name", flat=True))
        self.assertEqual(names, sorted(names))


class NothingIsDeletedTests(TestCase):
    def test_the_app_exposes_no_delete_service(self) -> None:
        for name in dir(services):
            self.assertFalse(
                name.startswith("delete_") or name.startswith("remove_"),
                f"clients.services exposes {name}; withdrawal must be retire_client.",
            )

    def test_contact_numbers_cascade_only_from_a_client_that_is_never_deleted(self) -> None:
        """CASCADE is safe here because no code path deletes a client."""
        admin = f.make_admin()
        client = f.make_client(admin, contact_numbers=[f.number()])

        self.assertEqual(ClientContactNumber.objects.filter(client=client).count(), 1)
        self.assertEqual(Client.objects.count(), 1)
