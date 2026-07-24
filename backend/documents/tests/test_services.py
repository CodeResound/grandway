"""Service-level tests for the documents app.

The load-bearing ones are `ContentIsStoredVerbatimTests` and
`ContentNeverReachesTheAuditLogTests`. Everything else in this app is ordinary
CRUD; those two encode the rules that make it correct.
"""

from __future__ import annotations

import copy

from audit.models import AuditEvent
from django.test import TestCase

from documents import services
from documents.constants import (
    AUDIT_APP_LABEL,
    CONTENT_CHANGE_MARKER,
    MAX_CONTENT_BYTES,
    DocumentAuditAction,
    DocumentStatus,
)
from documents.exceptions import (
    ArchiveReasonRequiredError,
    ContentInvalidError,
    ContentTooLargeError,
    DocumentAlreadyArchivedError,
    DocumentNotArchivedError,
    DocumentNotEditableError,
    InvalidStatusTransitionError,
    OwnerRequiredError,
    TemplateKeyInvalidError,
)
from documents.selectors import filter_documents, get_documents, get_workspace_summaries
from documents.tests import factories as f


class ContentIsStoredVerbatimTests(TestCase):
    """The single most important behaviour in this app.

    The frontend computes every derived value; the backend must return exactly
    what it was given, including keys it has never heard of.
    """

    @classmethod
    def setUpTestData(cls) -> None:
        cls.admin = f.make_admin()
        cls.applicant = f.make_applicant(cls.admin)

    def test_content_round_trips_unchanged(self) -> None:
        original = f.bank_statement_content()
        document = f.make_bank_statement(self.admin, self.applicant, content=copy.deepcopy(original))

        document.refresh_from_db()
        self.assertEqual(document.content, original)

    def test_unknown_keys_are_preserved(self) -> None:
        """Templates the backend has never heard of may depend on them."""
        content = {"totally_unknown_key": {"nested": [1, 2, 3]}, "another": "value"}
        document = f.make_document(self.admin, self.applicant, content=copy.deepcopy(content))

        document.refresh_from_db()
        self.assertEqual(document.content, content)

    def test_no_derived_value_is_injected(self) -> None:
        """The backend computes nothing — no balances, totals, or words."""
        document = f.make_bank_statement(self.admin, self.applicant)

        document.refresh_from_db()
        derived = (
            "statement_debit_total",
            "statement_credit_total",
            "statement_closing_balance",
            "statement_total_balance_words",
            "balance",
        )
        for key in derived:
            self.assertNotIn(key, document.content, f"backend injected derived field '{key}'")
        for row in document.content["transactions"]:
            self.assertNotIn("balance", row, "backend injected a running balance into a transaction row")

    def test_transaction_rows_keep_their_order(self) -> None:
        document = f.make_bank_statement(self.admin, self.applicant)

        document.refresh_from_db()
        dates = [row["date"] for row in document.content["transactions"]]
        self.assertEqual(dates, ["2026-04-01", "2026-05-12"])

    def test_a_client_supplied_derived_value_is_stored_not_stripped(self) -> None:
        """Documented gap: the backend does not police the body's contents.

        Stripping would violate "preserve any extra keys". The value is stored
        and must not be trusted — recorded in docs/INTEGRATION.md §9.
        """
        content = f.bank_statement_content()
        content["statement_debit_total"] = 999999
        document = f.make_bank_statement(self.admin, self.applicant, content=content)

        document.refresh_from_db()
        self.assertEqual(document.content["statement_debit_total"], 999999)

    def test_content_defaults_to_an_empty_object(self) -> None:
        """A workspace is opened before anything is typed into it."""
        document = f.make_document(self.admin, self.applicant)
        self.assertEqual(document.content, {})

    def test_a_non_object_body_is_rejected(self) -> None:
        for bad in ([1, 2, 3], "a string", 42):
            with self.subTest(bad=bad), self.assertRaises(ContentInvalidError):
                f.make_document(self.admin, self.applicant, content=bad)

    def test_an_oversized_body_is_rejected(self) -> None:
        oversized = {"rows": ["x" * 1000 for _ in range(MAX_CONTENT_BYTES // 1000 + 10)]}
        with self.assertRaises(ContentTooLargeError):
            f.make_document(self.admin, self.applicant, content=oversized)


class ContentNeverReachesTheAuditLogTests(TestCase):
    """§17 — the body holds financial data and must not be logged."""

    def setUp(self) -> None:
        self.admin = f.make_admin()
        self.applicant = f.make_applicant(self.admin)
        self.document = f.make_bank_statement(self.admin, self.applicant)

    def test_a_body_edit_records_a_marker_not_the_body(self) -> None:
        content = f.bank_statement_content()
        content["statement_account_no"] = "9999888877776"
        services.update_document(actor=self.admin, document=self.document, fields={"content": content})

        event = AuditEvent.objects.filter(action=DocumentAuditAction.DOCUMENT_UPDATED).first()
        self.assertIsNotNone(event)
        self.assertEqual(event.changes["content"], {"from": CONTENT_CHANGE_MARKER, "to": CONTENT_CHANGE_MARKER})

    def test_no_account_number_appears_anywhere_in_the_audit_trail(self) -> None:
        content = f.bank_statement_content()
        content["statement_account_no"] = "9999888877776"
        services.update_document(actor=self.admin, document=self.document, fields={"content": content})

        serialized = str(list(AuditEvent.objects.values("changes", "metadata", "summary")))
        self.assertNotIn("9999888877776", serialized)
        self.assertNotIn("0123456789012", serialized)

    def test_a_label_edit_still_records_its_before_and_after(self) -> None:
        """Only the body is redacted; ordinary fields are logged normally."""
        services.update_document(actor=self.admin, document=self.document, fields={"label": "Renamed"})

        event = AuditEvent.objects.filter(action=DocumentAuditAction.DOCUMENT_UPDATED).first()
        self.assertEqual(event.changes["label"], {"from": "Vyas Statement", "to": "Renamed"})


class OwnershipTests(TestCase):
    @classmethod
    def setUpTestData(cls) -> None:
        cls.admin = f.make_admin()
        cls.applicant = f.make_applicant(cls.admin)

    def test_applicant_owned_document(self) -> None:
        document = f.make_document(self.admin, self.applicant)

        self.assertEqual(document.applicant_id, self.applicant.id)
        self.assertFalse(document.is_standalone)

    def test_standalone_document_needs_a_purpose(self) -> None:
        with self.assertRaises(OwnerRequiredError):
            f.make_document(self.admin, None)

    def test_standalone_document_with_a_purpose(self) -> None:
        document = f.make_document(
            self.admin, None, standalone_purpose="Internal office letter commissioned by the director."
        )

        self.assertTrue(document.is_standalone)
        self.assertIsNone(document.applicant_id)

    def test_a_blank_purpose_does_not_count(self) -> None:
        with self.assertRaises(OwnerRequiredError):
            f.make_document(self.admin, None, standalone_purpose="   ")

    def test_clearing_the_purpose_of_a_standalone_document_is_rejected(self) -> None:
        document = f.make_document(self.admin, None, standalone_purpose="Internal letter.")
        with self.assertRaises(OwnerRequiredError):
            services.update_document(actor=self.admin, document=document, fields={"standalone_purpose": ""})


class TemplateKeyTests(TestCase):
    @classmethod
    def setUpTestData(cls) -> None:
        cls.admin = f.make_admin()
        cls.applicant = f.make_applicant(cls.admin)

    def test_family_and_slug_must_agree(self) -> None:
        with self.assertRaises(TemplateKeyInvalidError):
            f.make_document(self.admin, self.applicant, family="lor", template_key="bank-vyas-statement")

    def test_the_two_bank_families_are_told_apart_by_suffix(self) -> None:
        """Both share the `bank-` prefix, so the suffix is what distinguishes them."""
        with self.assertRaises(TemplateKeyInvalidError):
            f.make_document(self.admin, self.applicant, family="bank_certificate", template_key="bank-vyas-statement")

    def test_a_matching_bank_certificate_is_accepted(self) -> None:
        document = f.make_document(
            self.admin,
            self.applicant,
            family="bank_certificate",
            template_key="bank-vyas-certificate",
            label="Vyas Certificate",
        )
        self.assertEqual(document.template_key, "bank-vyas-certificate")

    def test_a_new_partner_slug_needs_no_code_change(self) -> None:
        """The point of the family/slug split — no enum, no migration."""
        document = f.make_document(
            self.admin,
            self.applicant,
            family="bank_statement",
            template_key="bank-brand-new-partner-statement",
            label="New Partner Statement",
        )
        self.assertEqual(document.template_key, "bank-brand-new-partner-statement")


class LifecycleTests(TestCase):
    def setUp(self) -> None:
        self.admin = f.make_admin()
        self.applicant = f.make_applicant(self.admin)
        self.document = f.make_document(self.admin, self.applicant)

    def test_a_document_starts_as_a_draft(self) -> None:
        self.assertEqual(self.document.status, DocumentStatus.DRAFT)
        self.assertTrue(self.document.is_editable)

    def test_mark_ready(self) -> None:
        updated = services.change_status(actor=self.admin, document=self.document, status=DocumentStatus.READY)
        self.assertEqual(updated.status, DocumentStatus.READY)

    def test_status_action_cannot_archive(self) -> None:
        with self.assertRaises(InvalidStatusTransitionError):
            services.change_status(actor=self.admin, document=self.document, status=DocumentStatus.ARCHIVED)

    def test_archive_requires_a_reason(self) -> None:
        with self.assertRaises(ArchiveReasonRequiredError):
            services.archive_document(actor=self.admin, document=self.document, reason="   ")

    def test_archive_stamps_who_and_why(self) -> None:
        archived = services.archive_document(
            actor=self.admin, document=self.document, reason="Superseded by the 2083 version."
        )

        self.assertEqual(archived.status, DocumentStatus.ARCHIVED)
        self.assertTrue(archived.is_archived)
        self.assertFalse(archived.is_editable)
        self.assertEqual(archived.archive_reason, "Superseded by the 2083 version.")
        self.assertEqual(archived.archived_by, self.admin)

    def test_an_archived_document_rejects_edits(self) -> None:
        services.archive_document(actor=self.admin, document=self.document, reason="Superseded.")
        with self.assertRaises(DocumentNotEditableError):
            services.update_document(actor=self.admin, document=self.document, fields={"label": "New"})

    def test_an_archived_document_rejects_status_changes(self) -> None:
        services.archive_document(actor=self.admin, document=self.document, reason="Superseded.")
        with self.assertRaises(DocumentNotEditableError):
            services.change_status(actor=self.admin, document=self.document, status=DocumentStatus.READY)

    def test_archiving_twice_is_rejected(self) -> None:
        services.archive_document(actor=self.admin, document=self.document, reason="Superseded.")
        with self.assertRaises(DocumentAlreadyArchivedError):
            services.archive_document(actor=self.admin, document=self.document, reason="Again.")

    def test_restore_always_returns_to_draft(self) -> None:
        """Never to `ready` — whoever archived it may have done so because it wasn't."""
        services.change_status(actor=self.admin, document=self.document, status=DocumentStatus.READY)
        services.archive_document(actor=self.admin, document=self.document, reason="Superseded.")
        restored = services.restore_document(actor=self.admin, document=self.document)

        self.assertEqual(restored.status, DocumentStatus.DRAFT)
        self.assertEqual(restored.archive_reason, "")
        self.assertIsNone(restored.archived_at)
        self.assertIsNone(restored.archived_by)

    def test_restoring_an_active_document_is_rejected(self) -> None:
        with self.assertRaises(DocumentNotArchivedError):
            services.restore_document(actor=self.admin, document=self.document)

    def test_restore_does_not_erase_the_archiving_from_history(self) -> None:
        services.archive_document(actor=self.admin, document=self.document, reason="Superseded.")
        services.restore_document(actor=self.admin, document=self.document)

        actions = set(AuditEvent.objects.filter(entity_id=str(self.document.id)).values_list("action", flat=True))
        self.assertIn(DocumentAuditAction.DOCUMENT_ARCHIVED, actions)
        self.assertIn(DocumentAuditAction.DOCUMENT_RESTORED, actions)

    def test_a_no_op_update_writes_no_event(self) -> None:
        services.update_document(actor=self.admin, document=self.document, fields={"label": "Certificate"})
        self.assertFalse(AuditEvent.objects.filter(action=DocumentAuditAction.DOCUMENT_UPDATED).exists())

    def test_creation_appends_one_audit_event(self) -> None:
        events = AuditEvent.objects.filter(app_label=AUDIT_APP_LABEL, entity_id=str(self.document.id))
        self.assertEqual(events.count(), 1)
        self.assertEqual(events.first().action, DocumentAuditAction.DOCUMENT_CREATED)


class SelectorTests(TestCase):
    @classmethod
    def setUpTestData(cls) -> None:
        cls.admin = f.make_admin()
        cls.applicant = f.make_applicant(cls.admin)
        cls.owned = f.make_document(cls.admin, cls.applicant, label="Certificate")
        cls.statement = f.make_bank_statement(cls.admin, cls.applicant, label="Vyas Statement")
        cls.standalone = f.make_document(cls.admin, None, standalone_purpose="Office letter.", label="Office Letter")

    def test_filter_by_applicant(self) -> None:
        found = filter_documents(get_documents(), {"applicant": str(self.applicant.id)})
        self.assertEqual(found.count(), 2)

    def test_filter_standalone(self) -> None:
        standalone = filter_documents(get_documents(), {"standalone": True})
        owned = filter_documents(get_documents(), {"standalone": False})

        self.assertEqual([d.id for d in standalone], [self.standalone.id])
        self.assertEqual(owned.count(), 2)

    def test_filter_by_family(self) -> None:
        found = filter_documents(get_documents(), {"family": "bank_statement"})
        self.assertEqual([d.id for d in found], [self.statement.id])

    def test_search_matches_labels(self) -> None:
        found = filter_documents(get_documents(), {"search": "Vyas"})
        self.assertEqual([d.id for d in found], [self.statement.id])

    def test_search_does_not_reach_into_the_body(self) -> None:
        """Full-text search over financial data needs its own decision."""
        found = filter_documents(get_documents(), {"search": "0123456789012"})
        self.assertEqual(found.count(), 0)

    def test_workspace_summary_groups_by_applicant(self) -> None:
        rows = list(get_workspace_summaries())

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["applicant_id"], self.applicant.id)
        self.assertEqual(rows[0]["document_count"], 2)

    def test_workspace_summary_excludes_standalone_documents(self) -> None:
        """They have no applicant to group under."""
        applicant_ids = [row["applicant_id"] for row in get_workspace_summaries()]
        self.assertNotIn(None, applicant_ids)

    def test_workspace_summary_excludes_archived_documents(self) -> None:
        services.archive_document(actor=self.admin, document=self.statement, reason="Superseded.")

        rows = list(get_workspace_summaries())
        self.assertEqual(rows[0]["document_count"], 1)

    def test_documents_are_ordered_most_recently_touched_first(self) -> None:
        services.update_document(actor=self.admin, document=self.owned, fields={"notes": "touched"})

        self.assertEqual(get_documents().first().id, self.owned.id)


class NothingIsDeletedTests(TestCase):
    def test_the_app_exposes_no_delete_service(self) -> None:
        for name in dir(services):
            self.assertFalse(
                name.startswith("delete_") or name.startswith("remove_"),
                f"documents.services exposes {name}; withdrawal must be archive_document.",
            )
