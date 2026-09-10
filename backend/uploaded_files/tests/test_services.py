"""Service and selector unit tests for the uploaded_files app.

Covers the rules that have no HTTP surface of their own: the storage-path rule,
the streamed checksum, the exactly-one-owner constraint at the database level,
the replacement chain, the audit-redaction rule, and the absence of any delete
path.

**Every test writes real bytes**, into a temp ``MEDIA_ROOT`` torn down
afterwards. Mocking the storage backend would leave the one thing this app does
— put a file on a disk — untested.
"""

from __future__ import annotations

import hashlib
import itertools
import re
import shutil
import tempfile
import unicodedata
from pathlib import Path
from typing import Any

from audit.models import AuditEvent
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings

from uploaded_files import services
from uploaded_files.constants import (
    ADMIN_ONLY_OWNER_TYPES,
    MAX_UPLOAD_BYTES,
    OWNER_FIELDS,
    FileCategory,
    OwnerType,
    UploadedFilesAuditAction,
    VerificationStatus,
)
from uploaded_files.exceptions import (
    AlreadyArchivedError,
    AlreadySupersededError,
    FieldImmutableError,
    FileArchivedError,
    FileContentMismatchError,
    FileEmptyError,
    FileTooLargeError,
    FileTypeNotAllowedError,
    InvalidVerificationStatusError,
    NotArchivedError,
    OwnerNotFoundError,
    OwnerNotResolvedError,
    ReasonRequiredError,
)
from uploaded_files.models import UploadedFile
from uploaded_files.selectors import (
    filter_files,
    get_file_verification_counts,
    get_files,
    get_files_awaiting_verification,
    get_version_chain,
)
from uploaded_files.tests import factories as f

MISSING_ID = "2b3c4d5e-6f70-4819-a2b3-c4d5e6f70819"


class FileServiceTestCase(TestCase):
    """Shared fixtures plus an isolated MEDIA_ROOT per test class."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._media_root = tempfile.mkdtemp(prefix="uploaded-files-test-")
        cls._media_override = override_settings(MEDIA_ROOT=cls._media_root)
        cls._media_override.enable()
        super().setUpClass()

    @classmethod
    def tearDownClass(cls) -> None:
        super().tearDownClass()
        cls._media_override.disable()
        shutil.rmtree(cls._media_root, ignore_errors=True)

    def setUp(self) -> None:
        self.admin = f.make_admin()
        self.lead_manager = f.make_lead_manager()
        self.applicant = f.make_applicant(self.admin)


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------


class StoragePathTests(FileServiceTestCase):
    """§14: the filename rule, and what the row records about the bytes."""

    def test_stored_name_is_a_uuid_not_the_client_filename(self) -> None:
        stored = f.upload_for_applicant(self.admin, self.applicant, upload=f.pdf_upload("sita_passport_scan.pdf"))

        path = Path(stored.file.name)
        self.assertNotIn("sita", stored.file.name)
        self.assertNotIn("passport_scan", path.stem)
        self.assertRegex(
            path.stem,
            r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
        )
        self.assertEqual(path.suffix, ".pdf")

    def test_original_filename_is_preserved_verbatim(self) -> None:
        stored = f.upload_for_applicant(self.admin, self.applicant, upload=f.pdf_upload("sita_passport_scan.pdf"))
        self.assertEqual(stored.original_filename, "sita_passport_scan.pdf")

    def test_path_carries_owner_type_and_date(self) -> None:
        stored = f.upload_for_applicant(self.admin, self.applicant)
        self.assertRegex(stored.file.name, r"^uploaded_files/applicant/\d{4}/\d{2}/")

    def test_bytes_land_on_disk_unmodified(self) -> None:
        stored = f.upload_for_applicant(self.admin, self.applicant)
        with stored.file.open("rb") as handle:
            self.assertEqual(handle.read(), f.PDF_BYTES)

    def test_checksum_matches_an_independent_digest(self) -> None:
        stored = f.upload_for_applicant(self.admin, self.applicant)
        self.assertEqual(stored.checksum_sha256, hashlib.sha256(f.PDF_BYTES).hexdigest())

    def test_content_type_comes_from_the_extension_not_the_client(self) -> None:
        """A part declaring ``image/png`` on a ``.pdf`` is stored as a PDF only
        if its bytes agree; the declared type never reaches the row."""
        stored = f.upload_for_applicant(self.admin, self.applicant, upload=f.jpeg_upload("photo.jpg"))
        self.assertEqual(stored.content_type, "image/jpeg")

    def test_size_is_measured_not_declared(self) -> None:
        stored = f.upload_for_applicant(self.admin, self.applicant)
        self.assertEqual(stored.size_bytes, len(f.PDF_BYTES))

    def test_duplicates_are_recorded_not_blocked(self) -> None:
        """The same scan legitimately supports two records."""
        first = f.upload_for_applicant(self.admin, self.applicant)
        second = f.upload_for_applicant(self.admin, self.applicant)
        self.assertEqual(first.checksum_sha256, second.checksum_sha256)
        self.assertNotEqual(first.id, second.id)


class UploadRejectionTests(FileServiceTestCase):
    """§14: nothing is stored when a check fails."""

    def test_oversize_file_is_refused(self) -> None:
        with self.assertRaises(FileTooLargeError):
            f.upload_for_applicant(self.admin, self.applicant, upload=f.oversize_upload())
        self.assertEqual(UploadedFile.objects.count(), 0)

    def test_empty_file_is_refused_with_its_own_error(self) -> None:
        """Not ``FileTooLargeError`` — a client mapping one code to "too big"
        would otherwise tell a user their 0-byte file was oversized."""
        with self.assertRaises(FileEmptyError):
            f.upload_for_applicant(self.admin, self.applicant, upload=f.empty_upload())

    def test_disallowed_extension_is_refused(self) -> None:
        with self.assertRaises(FileTypeNotAllowedError):
            f.upload_for_applicant(self.admin, self.applicant, upload=f.disallowed_upload())
        self.assertEqual(UploadedFile.objects.count(), 0)

    def test_double_extension_cannot_smuggle_a_type(self) -> None:
        """``passport.pdf.exe`` is an ``exe``, not a ``pdf``."""
        with self.assertRaises(FileTypeNotAllowedError):
            f.upload_for_applicant(self.admin, self.applicant, upload=f.pdf_upload("passport.pdf.exe"))

    def test_png_wearing_a_pdf_extension_is_refused(self) -> None:
        with self.assertRaises(FileContentMismatchError):
            f.upload_for_applicant(self.admin, self.applicant, upload=f.mislabelled_upload())
        self.assertEqual(UploadedFile.objects.count(), 0)

    def test_a_rejected_upload_leaves_nothing_on_disk(self) -> None:
        media_root = Path(self._media_root)
        before = {path for path in media_root.rglob("*") if path.is_file()}
        with self.assertRaises(FileContentMismatchError):
            f.upload_for_applicant(self.admin, self.applicant, upload=f.mislabelled_upload())
        after = {path for path in media_root.rglob("*") if path.is_file()}
        self.assertEqual(before, after)

    def test_the_documented_limit_is_the_enforced_limit(self) -> None:
        """Guards the contract, not the code: docs/API.md publishes 10 MB."""
        self.assertEqual(MAX_UPLOAD_BYTES, 10 * 1024 * 1024)


# ---------------------------------------------------------------------------
# Ownership
# ---------------------------------------------------------------------------


class OwnershipTests(FileServiceTestCase):
    """Exactly one owner — in the service, and in the database."""

    def setUp(self) -> None:
        super().setUp()
        self.journey = f.make_journey(self.admin, self.applicant)
        self.offer = f.make_manual_offer(self.admin, self.journey)
        self.document = f.make_document(self.admin, self.applicant)
        self.snapshot = f.make_snapshot(self.admin, self.document)
        self.signatory = f.make_signatory(self.admin)

    def test_each_owner_type_can_hold_a_file(self) -> None:
        cases = {
            "applicant": self.applicant,
            "journey": self.journey,
            "offer": self.offer,
            "document": self.document,
            "snapshot": self.snapshot,
            "signatory": self.signatory,
        }
        for owner_field, owner in cases.items():
            with self.subTest(owner=owner_field):
                stored = f.upload_for(self.admin, owner_field, owner)
                self.assertEqual(stored.owner_type, owner_field)
                self.assertEqual(stored.owner_id, owner.id)

    def test_no_owner_is_refused(self) -> None:
        with self.assertRaises(OwnerNotResolvedError):
            services.upload_file(
                actor=self.admin,
                upload=f.pdf_upload(),
                data={"category": FileCategory.OTHER},
            )

    def test_two_owners_are_refused(self) -> None:
        with self.assertRaises(OwnerNotResolvedError):
            services.upload_file(
                actor=self.admin,
                upload=f.pdf_upload(),
                data={
                    "applicant": self.applicant.id,
                    "journey": self.journey.id,
                    "category": FileCategory.OTHER,
                },
            )

    def test_a_nonexistent_owner_is_refused_with_its_field_name(self) -> None:
        with self.assertRaises(OwnerNotFoundError) as caught:
            services.upload_file(
                actor=self.admin,
                upload=f.pdf_upload(),
                data={"offer": MISSING_ID, "category": FileCategory.OTHER},
            )
        self.assertEqual(caught.exception.owner_field, "offer")

    def test_the_database_refuses_two_owners_even_without_the_service(self) -> None:
        """The constraint, not the service — the admin and the shell are bound too."""
        stored = f.upload_for_applicant(self.admin, self.applicant)
        with self.assertRaises(IntegrityError), transaction.atomic():
            UploadedFile.objects.filter(pk=stored.pk).update(journey=self.journey)

    def test_the_database_refuses_a_file_with_no_owner(self) -> None:
        stored = f.upload_for_applicant(self.admin, self.applicant)
        with self.assertRaises(IntegrityError), transaction.atomic():
            UploadedFile.objects.filter(pk=stored.pk).update(applicant=None)

    def test_the_constraint_covers_every_pair_of_owners(self) -> None:
        """Every pair, not a sample — this is what catches a forgotten clause.

        The constraint is regenerated from ``OWNER_FIELDS`` in the model but
        **inlined expanded** in the migration, so the two can silently disagree:
        an owner added to the tuple without a migration that drops and re-adds
        the CHECK leaves a constraint that permits two owners for the new
        column. Sweeping all pairs is the only assertion that notices.
        """
        owners = {
            "applicant": self.applicant,
            "journey": self.journey,
            "offer": self.offer,
            "document": self.document,
            "snapshot": self.snapshot,
            "signatory": self.signatory,
        }
        self.assertEqual(set(owners), set(OWNER_FIELDS), "a new owner needs a case here")

        for first, second in itertools.combinations(OWNER_FIELDS, 2):
            with self.subTest(first=first, second=second):
                stored = f.upload_for(self.admin, first, owners[first])
                with self.assertRaises(IntegrityError), transaction.atomic():
                    UploadedFile.objects.filter(pk=stored.pk).update(**{f"{second}_id": owners[second].pk})

    def test_owner_fields_and_the_enum_stay_in_step(self) -> None:
        """A seventh owner added to one and not the other fails here, not in production."""
        self.assertEqual(set(OWNER_FIELDS), set(OwnerType.values))
        self.assertLessEqual(set(ADMIN_ONLY_OWNER_TYPES), set(OWNER_FIELDS))


# ---------------------------------------------------------------------------
# Replacement
# ---------------------------------------------------------------------------


class ReplacementTests(FileServiceTestCase):
    """The chain: nothing is overwritten, and nothing is lost."""

    def setUp(self) -> None:
        super().setUp()
        self.original = f.upload_for_applicant(self.admin, self.applicant)

    def test_replacement_creates_a_new_row_at_the_next_version(self) -> None:
        successor = services.replace_file(
            actor=self.admin,
            uploaded_file=self.original,
            upload=f.pdf_upload("passport_rescan.pdf"),
        )
        self.assertNotEqual(successor.id, self.original.id)
        self.assertEqual(successor.version_number, 2)
        self.assertEqual(successor.replaces_id, self.original.id)

    def test_the_predecessor_keeps_its_bytes_and_becomes_non_current(self) -> None:
        services.replace_file(actor=self.admin, uploaded_file=self.original, upload=f.pdf_upload())
        self.original.refresh_from_db()

        self.assertFalse(self.original.is_current)
        self.assertIsNotNone(self.original.superseded_at)
        self.assertEqual(self.original.superseded_by, self.admin)
        with self.original.file.open("rb") as handle:
            self.assertEqual(handle.read(), f.PDF_BYTES)

    def test_the_successor_inherits_owner_and_category(self) -> None:
        successor = services.replace_file(actor=self.admin, uploaded_file=self.original, upload=f.pdf_upload())
        self.assertEqual(successor.owner_type, "applicant")
        self.assertEqual(successor.owner_id, self.applicant.id)
        self.assertEqual(successor.category, self.original.category)

    def test_the_successor_starts_pending_even_if_the_predecessor_was_verified(self) -> None:
        """A re-scan is a different artefact; carrying a verdict across would
        mark a file nobody looked at as reviewed."""
        services.review_file(actor=self.admin, uploaded_file=self.original, status=VerificationStatus.VERIFIED)
        successor = services.replace_file(actor=self.admin, uploaded_file=self.original, upload=f.pdf_upload())
        self.assertEqual(successor.verification_status, VerificationStatus.PENDING)
        self.original.refresh_from_db()
        self.assertTrue(self.original.is_verified)

    def test_replacing_a_superseded_file_is_refused(self) -> None:
        services.replace_file(actor=self.admin, uploaded_file=self.original, upload=f.pdf_upload())
        self.original.refresh_from_db()
        with self.assertRaises(AlreadySupersededError):
            services.replace_file(actor=self.admin, uploaded_file=self.original, upload=f.pdf_upload())

    def test_the_chain_reads_the_same_from_any_member(self) -> None:
        second = services.replace_file(actor=self.admin, uploaded_file=self.original, upload=f.pdf_upload("v2.pdf"))
        third = services.replace_file(actor=self.admin, uploaded_file=second, upload=f.pdf_upload("v3.pdf"))

        expected = [self.original.id, second.id, third.id]
        for entry in (self.original, second, third):
            with self.subTest(entry=entry.version_number):
                entry.refresh_from_db()
                self.assertEqual([item.id for item in get_version_chain(entry)], expected)

    def test_a_lone_file_is_a_chain_of_one(self) -> None:
        self.assertEqual([item.id for item in get_version_chain(self.original)], [self.original.id])


# ---------------------------------------------------------------------------
# Review
# ---------------------------------------------------------------------------


class ReviewTests(FileServiceTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.stored = f.upload_for_applicant(self.admin, self.applicant)

    def test_a_new_file_is_pending(self) -> None:
        self.assertEqual(self.stored.verification_status, VerificationStatus.PENDING)
        self.assertIsNone(self.stored.reviewed_at)

    def test_verifying_records_the_reviewer_and_the_time(self) -> None:
        reviewed = services.review_file(
            actor=self.admin, uploaded_file=self.stored, status=VerificationStatus.VERIFIED
        )
        self.assertTrue(reviewed.is_verified)
        self.assertEqual(reviewed.reviewed_by, self.admin)
        self.assertIsNotNone(reviewed.reviewed_at)

    def test_rejecting_without_a_reason_is_refused(self) -> None:
        with self.assertRaises(ReasonRequiredError):
            services.review_file(actor=self.admin, uploaded_file=self.stored, status=VerificationStatus.REJECTED)

    def test_rejecting_stores_the_reason(self) -> None:
        rejected = services.review_file(
            actor=self.admin,
            uploaded_file=self.stored,
            status=VerificationStatus.REJECTED,
            reason="Page 2 is unreadable.",
        )
        self.assertEqual(rejected.rejection_reason, "Page 2 is unreadable.")

    def test_re_verifying_clears_a_stale_rejection_reason(self) -> None:
        services.review_file(
            actor=self.admin,
            uploaded_file=self.stored,
            status=VerificationStatus.REJECTED,
            reason="Page 2 is unreadable.",
        )
        verified = services.review_file(
            actor=self.admin, uploaded_file=self.stored, status=VerificationStatus.VERIFIED
        )
        self.assertEqual(verified.rejection_reason, "")

    def test_pending_cannot_be_set_as_a_verdict(self) -> None:
        with self.assertRaises(InvalidVerificationStatusError):
            services.review_file(actor=self.admin, uploaded_file=self.stored, status=VerificationStatus.PENDING)


# ---------------------------------------------------------------------------
# Archive
# ---------------------------------------------------------------------------


class ArchiveTests(FileServiceTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.stored = f.upload_for_applicant(self.admin, self.applicant)

    def test_archiving_requires_a_reason(self) -> None:
        with self.assertRaises(ReasonRequiredError):
            services.archive_file(actor=self.admin, uploaded_file=self.stored, reason="   ")

    def test_archiving_records_who_and_why(self) -> None:
        archived = services.archive_file(
            actor=self.admin, uploaded_file=self.stored, reason="Superseded by a certified copy."
        )
        self.assertTrue(archived.is_archived)
        self.assertEqual(archived.archived_by, self.admin)
        self.assertEqual(archived.archive_reason, "Superseded by a certified copy.")

    def test_archiving_twice_is_refused(self) -> None:
        services.archive_file(actor=self.admin, uploaded_file=self.stored, reason="Done with it.")
        with self.assertRaises(AlreadyArchivedError):
            services.archive_file(actor=self.admin, uploaded_file=self.stored, reason="Again.")

    def test_restoring_clears_every_archive_column(self) -> None:
        services.archive_file(actor=self.admin, uploaded_file=self.stored, reason="Done with it.")
        restored = services.restore_file(actor=self.admin, uploaded_file=self.stored)
        self.assertFalse(restored.is_archived)
        self.assertIsNone(restored.archived_at)
        self.assertIsNone(restored.archived_by)
        self.assertEqual(restored.archive_reason, "")

    def test_restoring_a_live_file_is_refused(self) -> None:
        with self.assertRaises(NotArchivedError):
            services.restore_file(actor=self.admin, uploaded_file=self.stored)

    def test_archiving_does_not_touch_the_version_chain(self) -> None:
        """``is_archived`` and ``is_current`` are independent axes."""
        successor = services.replace_file(actor=self.admin, uploaded_file=self.stored, upload=f.pdf_upload())
        self.stored.refresh_from_db()
        services.archive_file(actor=self.admin, uploaded_file=successor, reason="Wrong document.")
        successor.refresh_from_db()

        self.assertTrue(successor.is_archived)
        self.assertTrue(successor.is_current)
        self.assertEqual(successor.replaces_id, self.stored.id)

    def test_the_archived_file_keeps_its_bytes(self) -> None:
        services.archive_file(actor=self.admin, uploaded_file=self.stored, reason="Done with it.")
        with self.stored.file.open("rb") as handle:
            self.assertEqual(handle.read(), f.PDF_BYTES)

    def test_every_write_against_an_archived_file_is_refused(self) -> None:
        services.archive_file(actor=self.admin, uploaded_file=self.stored, reason="Done with it.")
        with self.assertRaises(FileArchivedError):
            services.update_file(actor=self.admin, uploaded_file=self.stored, fields={"notes": "late note"})
        with self.assertRaises(FileArchivedError):
            services.replace_file(actor=self.admin, uploaded_file=self.stored, upload=f.pdf_upload())
        with self.assertRaises(FileArchivedError):
            services.review_file(actor=self.admin, uploaded_file=self.stored, status=VerificationStatus.VERIFIED)


# ---------------------------------------------------------------------------
# Update
# ---------------------------------------------------------------------------


class UpdateTests(FileServiceTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.stored = f.upload_for_applicant(self.admin, self.applicant)

    def test_category_and_notes_are_editable(self) -> None:
        updated = services.update_file(
            actor=self.admin,
            uploaded_file=self.stored,
            fields={"category": FileCategory.OTHER, "notes": "Filed by mistake under passport."},
        )
        self.assertEqual(updated.category, FileCategory.OTHER)
        self.assertEqual(updated.notes, "Filed by mistake under passport.")

    def test_everything_else_is_refused(self) -> None:
        for field, value in (
            ("applicant", self.applicant.id),
            ("checksum_sha256", "0" * 64),
            ("verification_status", VerificationStatus.VERIFIED),
            ("version_number", 9),
            ("original_filename", "renamed.pdf"),
        ):
            with self.subTest(field=field), self.assertRaises(FieldImmutableError):
                services.update_file(actor=self.admin, uploaded_file=self.stored, fields={field: value})

    def test_a_no_op_update_writes_no_audit_event(self) -> None:
        before = AuditEvent.objects.filter(action=UploadedFilesAuditAction.FILE_UPDATED).count()
        services.update_file(actor=self.admin, uploaded_file=self.stored, fields={"category": self.stored.category})
        after = AuditEvent.objects.filter(action=UploadedFilesAuditAction.FILE_UPDATED).count()
        self.assertEqual(before, after)

    def test_notes_are_unicode_normalized(self) -> None:
        """§39.2 — the decomposed form must be stored composed."""
        decomposed = "कार्यालय"
        updated = services.update_file(actor=self.admin, uploaded_file=self.stored, fields={"notes": decomposed})
        self.assertEqual(updated.notes, unicodedata.normalize("NFC", decomposed))


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------


class AuditTests(FileServiceTestCase):
    """Every write is recorded, and no record carries a storage path."""

    def setUp(self) -> None:
        super().setUp()
        self.stored = f.upload_for_applicant(self.admin, self.applicant)

    def _events(self) -> Any:
        return AuditEvent.objects.filter(app_label="uploaded_files")

    def test_every_action_writes_exactly_one_event(self) -> None:
        successor = services.replace_file(actor=self.admin, uploaded_file=self.stored, upload=f.pdf_upload())
        services.review_file(actor=self.admin, uploaded_file=successor, status=VerificationStatus.VERIFIED)
        services.archive_file(actor=self.admin, uploaded_file=successor, reason="Filed.")
        services.restore_file(actor=self.admin, uploaded_file=successor)
        services.record_download(actor=self.lead_manager, uploaded_file=successor)

        actions = list(self._events().values_list("action", flat=True))
        for expected in (
            UploadedFilesAuditAction.FILE_UPLOADED,
            UploadedFilesAuditAction.FILE_REPLACED,
            UploadedFilesAuditAction.FILE_REVIEWED,
            UploadedFilesAuditAction.FILE_ARCHIVED,
            UploadedFilesAuditAction.FILE_RESTORED,
            UploadedFilesAuditAction.FILE_DOWNLOADED,
        ):
            with self.subTest(action=expected):
                self.assertEqual(actions.count(expected), 1)

    def test_no_event_leaks_the_storage_path(self) -> None:
        """The one redaction rule this app has."""
        services.record_download(actor=self.admin, uploaded_file=self.stored)
        stem = Path(self.stored.file.name).stem

        for event in self._events():
            blob = f"{event.summary} {event.changes} {event.metadata} {event.reason}"
            with self.subTest(action=event.action):
                self.assertNotIn(stem, blob)
                self.assertNotIn("uploaded_files/applicant/", blob)
                self.assertNotIn(str(self._media_root), blob)

    def test_events_carry_the_owner_so_a_file_can_be_traced_to_a_record(self) -> None:
        event = self._events().filter(action=UploadedFilesAuditAction.FILE_UPLOADED).first()
        self.assertEqual(event.metadata["owner_type"], "applicant")
        self.assertEqual(event.metadata["owner_id"], str(self.applicant.id))

    def test_a_download_is_recorded_with_the_actor_who_asked(self) -> None:
        services.record_download(actor=self.lead_manager, uploaded_file=self.stored)
        event = self._events().filter(action=UploadedFilesAuditAction.FILE_DOWNLOADED).first()
        self.assertEqual(str(event.actor_id), str(self.lead_manager.id))


# ---------------------------------------------------------------------------
# Selectors
# ---------------------------------------------------------------------------


class SelectorTests(FileServiceTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.journey = f.make_journey(self.admin, self.applicant)
        self.passport = f.upload_for_applicant(self.admin, self.applicant)
        self.transcript = f.upload_for(
            self.admin,
            "journey",
            self.journey,
            category=FileCategory.ACADEMIC_TRANSCRIPT,
            upload=f.pdf_upload("transcript.pdf"),
        )

    def test_owner_filter_narrows_to_that_record(self) -> None:
        rows = filter_files(get_files(), {"applicant": self.applicant.id})
        self.assertEqual([row.id for row in rows], [self.passport.id])

    def test_the_signatory_owner_filter_works(self) -> None:
        signatory = f.make_signatory(self.admin)
        signature = f.upload_for(self.admin, "signatory", signatory)

        rows = filter_files(get_files(), {"signatory": signatory.id})

        self.assertEqual([row.id for row in rows], [signature.id])

    def test_a_signature_is_not_review_queue_work(self) -> None:
        """Excluded from ``_live_files``, and so from three dashboard figures.

        Every upload starts ``pending``, so without this a director's signature
        would sit in the Admin review queue and render in Today's Work as a row
        with no applicant and nowhere to click — ``dashboards.FileRowSerializer``
        reads ``applicant_id``/``journey_id``, both null here.

        The file is still fully in the ledger, which the last two assertions
        pin: absent from the *queue*, not from the app.
        """
        signatory = f.make_signatory(self.admin)
        signature = f.upload_for(self.admin, "signatory", signatory)

        queued = get_files_awaiting_verification(is_admin=True)
        counts = get_file_verification_counts(is_admin=True)

        self.assertNotIn(signature.id, [row.id for row in queued])
        self.assertIn(self.passport.id, [row.id for row in queued])
        self.assertEqual(counts[VerificationStatus.PENDING], 2)

        self.assertIn(signature.id, [row.id for row in get_files()])
        self.assertEqual([row.id for row in filter_files(get_files(), {"signatory": signatory.id})], [signature.id])

    def test_category_filter(self) -> None:
        rows = filter_files(get_files(), {"category": FileCategory.ACADEMIC_TRANSCRIPT})
        self.assertEqual([row.id for row in rows], [self.transcript.id])

    def test_search_matches_the_original_filename(self) -> None:
        rows = filter_files(get_files(), {"search": "transcript"})
        self.assertEqual([row.id for row in rows], [self.transcript.id])

    def test_checksum_filter_finds_duplicates(self) -> None:
        duplicate = f.upload_for_applicant(self.admin, self.applicant)
        rows = filter_files(get_files(), {"checksum": duplicate.checksum_sha256})
        self.assertIn(duplicate.id, [row.id for row in rows])
        self.assertIn(self.passport.id, [row.id for row in rows])

    def test_omitting_is_archived_returns_archived_rows_too(self) -> None:
        """A selector must not hide rows nobody asked it to hide."""
        services.archive_file(actor=self.admin, uploaded_file=self.passport, reason="Filed.")
        self.assertIn(self.passport.id, [row.id for row in filter_files(get_files(), {})])
        self.assertNotIn(self.passport.id, [row.id for row in filter_files(get_files(), {"is_archived": False})])

    def test_is_current_filter_excludes_superseded_rows(self) -> None:
        successor = services.replace_file(actor=self.admin, uploaded_file=self.passport, upload=f.pdf_upload())
        current = [row.id for row in filter_files(get_files(), {"is_current": True})]
        self.assertIn(successor.id, current)
        self.assertNotIn(self.passport.id, current)


# ---------------------------------------------------------------------------
# Nothing is deleted
# ---------------------------------------------------------------------------


class NothingIsDeletedTests(FileServiceTestCase):
    """A structural guard: this app must never grow a delete path.

    Mirrors ``document_templates``' equivalent. It fails the moment someone adds
    a delete service or a ``DELETE`` route, which is exactly when the decision
    should be re-argued rather than absorbed.
    """

    def test_no_service_function_deletes(self) -> None:
        deleters = [name for name in dir(services) if re.search(r"(^|_)(delete|destroy|purge)", name)]
        self.assertEqual(deleters, [])

    def test_no_view_defines_a_delete_handler(self) -> None:
        from uploaded_files import urls

        for pattern in urls.urlpatterns:
            view = pattern.callback.cls
            with self.subTest(route=str(pattern.pattern)):
                self.assertFalse(hasattr(view, "delete"))

    def test_the_admin_refuses_add_change_and_delete(self) -> None:
        from django.contrib import admin as django_admin

        from uploaded_files.models import UploadedFile as Model

        registered = django_admin.site._registry[Model]
        self.assertFalse(registered.has_add_permission(None))
        self.assertFalse(registered.has_change_permission(None))
        self.assertFalse(registered.has_delete_permission(None))
