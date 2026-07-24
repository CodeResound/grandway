"""Service and model tests for the document_history app.

The load-bearing test in this file is
``SnapshotFreezesTheBodyTests::test_editing_the_document_does_not_change_the_snapshot``.
Every other guarantee in this module is a convenience; that one is the module's
entire reason to exist, and if it ever fails the print history is a lie.
"""

from __future__ import annotations

import unicodedata
from typing import Any

from audit.models import AuditEvent
from django.db import IntegrityError, transaction
from django.test import TestCase
from documents import services as document_services
from documents.exceptions import DocumentNotEditableError

from document_history import services
from document_history.constants import (
    AUDIT_APP_LABEL,
    MAX_RENDER_CONTEXT_BYTES,
    DocumentHistoryAuditAction,
    PrintEventType,
)
from document_history.exceptions import (
    RenderContextInvalidError,
    RenderContextTooLargeError,
    SnapshotImmutableError,
)
from document_history.models import DocumentSnapshot, PrintEvent
from document_history.tests import factories as f


class DocumentHistoryTestCase(TestCase):
    """Shared fixtures: an Admin, an applicant, and a bank statement to freeze."""

    def setUp(self) -> None:
        self.admin = f.make_admin()
        self.applicant = f.make_applicant(self.admin)
        self.document = f.make_bank_statement(self.admin, self.applicant)


class VersionChainTests(DocumentHistoryTestCase):
    """Version numbers are allocated by the server, 1-based, and per document."""

    def test_first_snapshot_is_version_one(self) -> None:
        snapshot = f.make_snapshot(self.admin, self.document)
        self.assertEqual(snapshot.version_number, 1)

    def test_versions_increment_within_one_document(self) -> None:
        versions = [f.make_snapshot(self.admin, self.document).version_number for _ in range(3)]
        self.assertEqual(versions, [1, 2, 3])

    def test_chains_are_independent_across_documents(self) -> None:
        other = f.make_document(self.admin, self.applicant, label="Certificate")
        f.make_snapshot(self.admin, self.document)
        f.make_snapshot(self.admin, self.document)

        first_of_other = f.make_snapshot(self.admin, other)

        self.assertEqual(first_of_other.version_number, 1)

    def test_a_duplicate_version_number_is_refused_by_the_database(self) -> None:
        """The unique constraint is the backstop behind the row lock."""
        snapshot = f.make_snapshot(self.admin, self.document)

        with self.assertRaises(IntegrityError), transaction.atomic():
            DocumentSnapshot.objects.create(
                document=self.document,
                version_number=snapshot.version_number,
                family=self.document.family,
                template_key=self.document.template_key,
                label=self.document.label,
                captured_by=self.admin,
            )


class SnapshotFreezesTheBodyTests(DocumentHistoryTestCase):
    """The module's core guarantee."""

    def test_snapshot_copies_the_body_from_the_document(self) -> None:
        snapshot = f.make_snapshot(self.admin, self.document)
        self.assertEqual(snapshot.content, self.document.content)

    def test_editing_the_document_does_not_change_the_snapshot(self) -> None:
        """`concepts/project_overview.txt` — "Immutable print history"."""
        snapshot = f.make_snapshot(self.admin, self.document)
        original_content = dict(snapshot.content)

        document_services.update_document(
            actor=self.admin,
            document=self.document,
            fields={"content": {"statement_account_holder": "Someone Else"}, "label": "Renamed"},
        )

        snapshot.refresh_from_db()
        self.assertEqual(snapshot.content, original_content)
        self.assertEqual(snapshot.label, "Vyas Statement")

    def test_identity_fields_are_copied_not_read_through(self) -> None:
        snapshot = f.make_snapshot(self.admin, self.document)

        document_services.update_document(actor=self.admin, document=self.document, fields={"label": "Renamed"})

        snapshot.refresh_from_db()
        self.document.refresh_from_db()
        self.assertEqual(snapshot.label, "Vyas Statement")
        self.assertEqual(self.document.label, "Renamed")

    def test_render_context_is_stored_verbatim(self) -> None:
        context = f.render_context(unknown_key_a_template_needs="preserved")
        snapshot = f.make_snapshot(self.admin, self.document, render_context=context)

        snapshot.refresh_from_db()
        self.assertEqual(snapshot.render_context, context)

    def test_an_archived_document_can_still_be_captured(self) -> None:
        """A freeze is a read; only recovery respects the archive lock."""
        document_services.archive_document(actor=self.admin, document=self.document, reason="Superseded.")

        snapshot = f.make_snapshot(self.admin, self.document)

        self.assertEqual(snapshot.version_number, 1)


class RenderContextValidationTests(DocumentHistoryTestCase):
    def test_a_non_object_render_context_is_refused(self) -> None:
        with self.assertRaises(RenderContextInvalidError):
            services.create_snapshot(actor=self.admin, document=self.document, render_context=["not", "an", "object"])

    def test_an_oversized_render_context_is_refused(self) -> None:
        oversized = {"computed": {f"key_{i}": "x" * 64 for i in range(MAX_RENDER_CONTEXT_BYTES // 32)}}

        with self.assertRaises(RenderContextTooLargeError):
            services.create_snapshot(actor=self.admin, document=self.document, render_context=oversized)

    def test_no_snapshot_is_written_when_the_render_context_is_refused(self) -> None:
        with self.assertRaises(RenderContextInvalidError):
            services.create_snapshot(actor=self.admin, document=self.document, render_context="nope")

        self.assertEqual(DocumentSnapshot.objects.count(), 0)


class ImmutabilityTests(DocumentHistoryTestCase):
    """`concepts/document_history.txt` — no editing, no deletion, ever."""

    def test_a_stored_snapshot_cannot_be_saved_again(self) -> None:
        snapshot = f.make_snapshot(self.admin, self.document)
        snapshot.label = "Tampered"

        with self.assertRaises(SnapshotImmutableError):
            snapshot.save()

    def test_a_snapshot_cannot_be_deleted(self) -> None:
        snapshot = f.make_snapshot(self.admin, self.document)

        with self.assertRaises(SnapshotImmutableError):
            snapshot.delete()

    def test_a_print_event_cannot_be_deleted(self) -> None:
        f.make_snapshot(self.admin, self.document)
        event = PrintEvent.objects.get()

        with self.assertRaises(SnapshotImmutableError):
            event.delete()

    def test_no_update_or_delete_service_exists(self) -> None:
        """Fails if a future session adds one without revisiting this contract."""
        forbidden = {"update_snapshot", "delete_snapshot", "edit_snapshot", "remove_snapshot"}
        self.assertEqual(forbidden & set(dir(services)), set())


class PrintEventTests(DocumentHistoryTestCase):
    """Which action writes a snapshot, and which writes only an event."""

    def test_capture_writes_exactly_one_capture_event(self) -> None:
        snapshot = f.make_snapshot(self.admin, self.document)

        events = PrintEvent.objects.filter(snapshot=snapshot)
        self.assertEqual(events.count(), 1)
        self.assertEqual(events.get().event_type, PrintEventType.CAPTURE)

    def test_print_event_carries_the_denormalized_document(self) -> None:
        snapshot = f.make_snapshot(self.admin, self.document)
        event = PrintEvent.objects.get()

        self.assertEqual(event.document_id, snapshot.document_id)

    def test_capture_event_carries_the_snapshots_capture_note(self) -> None:
        """A timeline row and the Snapshot Detail screen must show the same note.

        Documented in ``docs/INTEGRATION.md`` §4, so it is contract rather than
        incidental — the two fields have different names and a future refactor
        could plausibly decouple them.
        """
        snapshot = f.make_snapshot(self.admin, self.document, capture_note="Printed for the visa file.")

        event = PrintEvent.objects.get(snapshot=snapshot)

        self.assertEqual(event.note, snapshot.capture_note)

    def test_a_document_with_an_empty_body_can_be_captured(self) -> None:
        """Nothing rejects a blank capture; the snapshot records that it was blank."""
        blank = f.make_document(self.admin, self.applicant, label="Blank")

        snapshot = f.make_snapshot(self.admin, blank)

        self.assertEqual(snapshot.content, {})
        self.assertEqual(snapshot.version_number, 1)

    def test_reprint_writes_an_event_and_no_new_snapshot(self) -> None:
        snapshot = f.make_snapshot(self.admin, self.document)

        services.reprint_snapshot(actor=self.admin, snapshot=snapshot, note="Second copy for the bank.")

        self.assertEqual(DocumentSnapshot.objects.count(), 1)
        self.assertEqual(PrintEvent.objects.filter(event_type=PrintEventType.REPRINT).count(), 1)

    def test_reprint_does_not_touch_the_document(self) -> None:
        snapshot = f.make_snapshot(self.admin, self.document)
        before = self.document.updated_at

        services.reprint_snapshot(actor=self.admin, snapshot=snapshot)

        self.document.refresh_from_db()
        self.assertEqual(self.document.updated_at, before)


class RecoveryTests(DocumentHistoryTestCase):
    """Recovery writes forward into the working document and never backward."""

    def setUp(self) -> None:
        super().setUp()
        self.snapshot = f.make_snapshot(self.admin, self.document)
        document_services.update_document(
            actor=self.admin,
            document=self.document,
            fields={"content": {"statement_account_holder": "Someone Else"}, "label": "Renamed"},
        )

    def test_recovery_restores_the_frozen_label_and_body(self) -> None:
        document = services.recover_snapshot(actor=self.admin, snapshot=self.snapshot)

        self.assertEqual(document.content, self.snapshot.content)
        self.assertEqual(document.label, "Vyas Statement")

    def test_recovery_leaves_the_snapshot_untouched(self) -> None:
        original = dict(self.snapshot.content)

        services.recover_snapshot(actor=self.admin, snapshot=self.snapshot)

        self.snapshot.refresh_from_db()
        self.assertEqual(self.snapshot.content, original)

    def test_recovery_creates_no_new_snapshot(self) -> None:
        services.recover_snapshot(actor=self.admin, snapshot=self.snapshot)

        self.assertEqual(DocumentSnapshot.objects.count(), 1)

    def test_recovery_writes_a_recovery_event(self) -> None:
        services.recover_snapshot(actor=self.admin, snapshot=self.snapshot)

        self.assertEqual(PrintEvent.objects.filter(event_type=PrintEventType.RECOVERY).count(), 1)

    def test_recovery_does_not_restore_notes_or_status(self) -> None:
        """A note written after the print survives; a `ready` document stays ready."""
        document_services.update_document(
            actor=self.admin,
            document=self.document,
            fields={"notes": "Written after the print."},
        )
        document_services.change_status(actor=self.admin, document=self.document, status="ready")

        document = services.recover_snapshot(actor=self.admin, snapshot=self.snapshot)

        self.assertEqual(document.notes, "Written after the print.")
        self.assertEqual(document.status, "ready")

    def test_recovery_into_an_archived_document_is_refused(self) -> None:
        document_services.archive_document(actor=self.admin, document=self.document, reason="Superseded.")

        with self.assertRaises(DocumentNotEditableError):
            services.recover_snapshot(actor=self.admin, snapshot=self.snapshot)

    def test_a_no_op_recovery_still_records_the_action(self) -> None:
        """The body already matches, so `documents` writes nothing — this app must."""
        services.recover_snapshot(actor=self.admin, snapshot=self.snapshot)
        recovery_events_before = PrintEvent.objects.filter(event_type=PrintEventType.RECOVERY).count()

        services.recover_snapshot(actor=self.admin, snapshot=self.snapshot)

        self.assertEqual(
            PrintEvent.objects.filter(event_type=PrintEventType.RECOVERY).count(),
            recovery_events_before + 1,
        )
        self.assertEqual(
            AuditEvent.objects.filter(
                app_label=AUDIT_APP_LABEL,
                action=DocumentHistoryAuditAction.SNAPSHOT_RECOVERED,
            ).count(),
            2,
        )


class AuditTrailTests(DocumentHistoryTestCase):
    def _events(self, action: str) -> Any:
        return AuditEvent.objects.filter(app_label=AUDIT_APP_LABEL, action=action)

    def test_capture_appends_one_event(self) -> None:
        f.make_snapshot(self.admin, self.document)
        self.assertEqual(self._events(DocumentHistoryAuditAction.SNAPSHOT_CAPTURED).count(), 1)

    def test_reprint_appends_one_event(self) -> None:
        snapshot = f.make_snapshot(self.admin, self.document)
        services.reprint_snapshot(actor=self.admin, snapshot=snapshot)
        self.assertEqual(self._events(DocumentHistoryAuditAction.SNAPSHOT_REPRINTED).count(), 1)

    def test_recovery_appends_one_event_in_each_app(self) -> None:
        snapshot = f.make_snapshot(self.admin, self.document)
        document_services.update_document(actor=self.admin, document=self.document, fields={"label": "Renamed"})

        services.recover_snapshot(actor=self.admin, snapshot=snapshot)

        self.assertEqual(self._events(DocumentHistoryAuditAction.SNAPSHOT_RECOVERED).count(), 1)
        self.assertEqual(
            AuditEvent.objects.filter(app_label="documents", action="document_updated").count(),
            2,  # the rename above, then the recovery's own write
        )

    def test_event_metadata_carries_identity_and_position(self) -> None:
        snapshot = f.make_snapshot(self.admin, self.document)
        event = self._events(DocumentHistoryAuditAction.SNAPSHOT_CAPTURED).get()

        self.assertEqual(event.metadata["document_id"], str(self.document.id))
        self.assertEqual(event.metadata["version_number"], snapshot.version_number)
        self.assertEqual(event.metadata["event_type"], PrintEventType.CAPTURE)


class FrozenPayloadNeverReachesTheAuditLogTests(DocumentHistoryTestCase):
    """§17. The audit log is readable by every Admin and Superadmin.

    ``content`` holds an applicant's account number and transaction history;
    ``render_context`` additionally holds their computed closing balance.
    Neither may ever be written into an audit event, in any field.
    """

    def test_no_audit_event_contains_the_body_or_the_render_context(self) -> None:
        account_no = f.bank_statement_content()["statement_account_no"]
        closing_balance = str(f.render_context()["computed"]["statement_closing_balance"])

        snapshot = f.make_snapshot(self.admin, self.document)
        services.reprint_snapshot(actor=self.admin, snapshot=snapshot)
        services.recover_snapshot(actor=self.admin, snapshot=snapshot)

        for event in AuditEvent.objects.filter(app_label=AUDIT_APP_LABEL):
            serialized = f"{event.summary}{event.reason}{event.changes}{event.metadata}"
            self.assertNotIn(account_no, serialized)
            self.assertNotIn(closing_balance, serialized)


class NepalLocalizationTests(DocumentHistoryTestCase):
    """§39.2 — user-entered text is Unicode-normalized on write.

    Both forms are built from explicit codepoint escapes rather than written as
    literal Devanagari. A literal typed into a source file is fragile: an
    editor, a formatter, or a checkout filter may silently fold it, at which
    point the test passes without exercising normalization at all.

    **Note which direction NFC moves Devanagari.** U+0958–U+095F (the
    precomposed nukta letters) are Unicode *composition exclusions*, so NFC
    does **not** produce them — it leaves the two-codepoint sequence, and
    normalizes the precomposed character *into* that sequence. Storage
    therefore converges on the decomposed pair, which is the property that
    matters: two visually identical inputs end up byte-identical in the
    database and match each other in a search.
    """

    #: DEVANAGARI LETTER QA — the single precomposed codepoint.
    PRECOMPOSED = "\u0958"
    #: DEVANAGARI LETTER KA + DEVANAGARI SIGN NUKTA — what NFC yields instead.
    NORMALIZED = "\u0915\u093c"

    def setUp(self) -> None:
        super().setUp()
        # Guard the fixture itself: if these ever stop differing, or if NFC
        # stops mapping one to the other, the assertions below prove nothing.
        self.assertNotEqual(self.PRECOMPOSED, self.NORMALIZED)
        self.assertEqual(unicodedata.normalize("NFC", self.PRECOMPOSED), self.NORMALIZED)

    def test_capture_note_is_normalized(self) -> None:
        snapshot = f.make_snapshot(self.admin, self.document, capture_note=self.PRECOMPOSED)

        self.assertEqual(snapshot.capture_note, self.NORMALIZED)

    def test_reprint_note_is_normalized(self) -> None:
        snapshot = f.make_snapshot(self.admin, self.document)

        event = services.reprint_snapshot(actor=self.admin, snapshot=snapshot, note=self.PRECOMPOSED)

        self.assertEqual(event.note, self.NORMALIZED)

    def test_two_spellings_of_the_same_note_converge_in_storage(self) -> None:
        """The point of §39.2, stated as the behaviour staff actually depend on."""
        first = f.make_snapshot(self.admin, self.document, capture_note=self.PRECOMPOSED)
        second = f.make_snapshot(self.admin, self.document, capture_note=self.NORMALIZED)

        self.assertEqual(first.capture_note, second.capture_note)
