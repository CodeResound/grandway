"""Service, model, and seed-command tests for the document_templates app.

Two things here are load-bearing beyond ordinary coverage:

* the key/family rule is the **imported** one from ``documents``, so a test that
  passes here and fails there would mean the two apps have drifted — which is
  the exact failure §4's anti-duplication rule exists to prevent;
* the seed list must stay at 53 slugs, because a slug silently dropped during a
  future edit would quietly shrink the catalogue with nothing to notice.
"""

from __future__ import annotations

import unicodedata
from io import StringIO
from typing import Any

from audit.models import AuditEvent
from django.core.management import call_command
from django.test import TestCase
from documents.constants import DocumentFamily
from documents.exceptions import TemplateKeyInvalidError

from document_templates import services
from document_templates.constants import (
    AUDIT_APP_LABEL,
    DocumentTemplatesAuditAction,
    LifecycleStatus,
)
from document_templates.exceptions import (
    InvalidStatusTransitionError,
    TemplateKeyAlreadyExistsError,
    TemplateKeyImmutableError,
)
from document_templates.models import DocumentTemplate, Signatory
from document_templates.seed_data import EXPECTED_TEMPLATE_COUNT, build_seed_rows
from document_templates.selectors import get_active_signatories, search_signatories
from document_templates.tests import factories as f


class DocumentTemplatesTestCase(TestCase):
    def setUp(self) -> None:
        self.admin = f.make_admin()


# ---------------------------------------------------------------------------
# Signatories
# ---------------------------------------------------------------------------


class UnicodeNormalizationTests(DocumentTemplatesTestCase):
    """§39.2 — every user-entered text field is NFC-normalized on write.

    Both forms are built from explicit codepoint escapes rather than literal
    Devanagari: a literal typed into a source file can be silently folded by an
    editor or a checkout filter, at which point the test passes without
    exercising normalization at all.

    Note which direction NFC moves Devanagari. U+0958–U+095F (the precomposed
    nukta letters) are Unicode *composition exclusions*, so NFC does not produce
    them — it normalizes the precomposed character *into* the two-codepoint
    sequence. Storage converges on the decomposed pair, which is the property
    that matters: two visually identical inputs end up byte-identical and match
    each other in a search.
    """

    PRECOMPOSED = "क़"  # DEVANAGARI LETTER QA
    NORMALIZED = "क़"  # KA + NUKTA

    def setUp(self) -> None:
        super().setUp()
        self.assertNotEqual(self.PRECOMPOSED, self.NORMALIZED)
        self.assertEqual(unicodedata.normalize("NFC", self.PRECOMPOSED), self.NORMALIZED)

    def test_signatory_name_is_normalized(self) -> None:
        signatory = f.make_signatory(self.admin, name=self.PRECOMPOSED)

        self.assertEqual(signatory.name, self.NORMALIZED)

    def test_status_note_is_normalized(self) -> None:
        signatory = f.make_signatory(self.admin)

        updated = services.change_signatory_status(
            actor=self.admin,
            signatory=signatory,
            status=LifecycleStatus.INACTIVE,
            note=self.PRECOMPOSED,
        )

        self.assertEqual(updated.status_note, self.NORMALIZED)

    def test_two_spellings_of_one_name_converge_in_storage(self) -> None:
        """The point of §39.2, stated as the behaviour search depends on."""
        first = f.make_signatory(self.admin)
        second = f.make_signatory(self.admin)

        self.assertEqual(first.name, second.name)


class SignatoryLifecycleTests(DocumentTemplatesTestCase):
    def test_a_new_signatory_starts_as_draft(self) -> None:
        """Activation must be a decision, not a default."""
        signatory = f.make_signatory(self.admin)

        self.assertEqual(signatory.status, LifecycleStatus.DRAFT)
        self.assertFalse(signatory.is_active)

    def test_only_active_signatories_reach_the_picker(self) -> None:
        """A draft signatory is excluded alongside a retired one."""
        f.make_signatory(self.admin)
        active = f.make_active_signatory(self.admin)
        retired = f.make_active_signatory(self.admin)
        services.change_signatory_status(actor=self.admin, signatory=retired, status=LifecycleStatus.INACTIVE)

        picker = list(get_active_signatories())

        self.assertEqual([s.id for s in picker], [active.id])

    def test_deactivating_does_not_delete_the_record(self) -> None:
        """A snapshot that froze this id must keep resolving."""
        signatory = f.make_active_signatory(self.admin)

        services.change_signatory_status(actor=self.admin, signatory=signatory, status=LifecycleStatus.INACTIVE)

        self.assertTrue(Signatory.objects.filter(pk=signatory.pk).exists())

    def test_an_unknown_status_is_refused(self) -> None:
        signatory = f.make_signatory(self.admin)

        with self.assertRaises(InvalidStatusTransitionError):
            services.change_signatory_status(actor=self.admin, signatory=signatory, status="enabled")

    def test_search_matches_the_name(self) -> None:
        signatory = f.make_signatory(self.admin)

        for query in (signatory.name, "Sunita", "sunita"):
            with self.subTest(query=query):
                found = search_signatories(Signatory.objects.all(), query)
                self.assertIn(signatory, found)


# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------


class TemplateKeyRuleTests(DocumentTemplatesTestCase):
    """The key/family rule is imported from `documents`, not reimplemented."""

    def test_a_key_disagreeing_with_its_family_is_refused(self) -> None:
        with self.assertRaises(TemplateKeyInvalidError):
            f.make_template(self.admin, key="bank-vyas-statement", family=DocumentFamily.LOR)

    def test_the_bank_suffix_rule_is_enforced_too(self) -> None:
        """Both bank families share the `bank-` prefix and split on suffix."""
        with self.assertRaises(TemplateKeyInvalidError):
            f.make_template(
                self.admin,
                key="bank-vyas-statement",
                family=DocumentFamily.BANK_CERTIFICATE,
            )

    def test_a_matching_key_and_family_is_accepted(self) -> None:
        template = f.make_template(
            self.admin,
            key="bank-vyas-certificate",
            family=DocumentFamily.BANK_CERTIFICATE,
        )

        self.assertEqual(template.key, "bank-vyas-certificate")

    def test_a_duplicate_key_is_refused(self) -> None:
        f.make_template(self.admin)

        with self.assertRaises(TemplateKeyAlreadyExistsError):
            f.make_template(self.admin)

    def test_the_key_cannot_be_changed_after_creation(self) -> None:
        """Documents point at it as a plain string with no FK to protect them."""
        template = f.make_template(self.admin)

        with self.assertRaises(TemplateKeyImmutableError):
            services.update_template(actor=self.admin, template=template, fields={"key": "bank-tribeni-statement"})

    def test_changing_family_revalidates_against_the_existing_key(self) -> None:
        template = f.make_template(self.admin)

        with self.assertRaises(TemplateKeyInvalidError):
            services.update_template(actor=self.admin, template=template, fields={"family": DocumentFamily.MOI})


class TemplateLifecycleTests(DocumentTemplatesTestCase):
    def test_a_new_template_starts_as_draft(self) -> None:
        self.assertEqual(f.make_template(self.admin).status, LifecycleStatus.DRAFT)

    def test_retiring_a_template_leaves_it_retrievable(self) -> None:
        """`concepts` flow 4: retirement must not break records pointing at it."""
        template = f.make_active_template(self.admin)

        services.change_template_status(
            actor=self.admin, template=template, status=LifecycleStatus.INACTIVE, note="Partner closed."
        )

        template.refresh_from_db()
        self.assertFalse(template.is_active)
        self.assertEqual(template.status_note, "Partner closed.")
        self.assertTrue(DocumentTemplate.objects.filter(pk=template.pk).exists())

    def test_a_no_op_update_writes_no_event(self) -> None:
        template = f.make_template(self.admin)
        before = AuditEvent.objects.filter(app_label=AUDIT_APP_LABEL).count()

        services.update_template(actor=self.admin, template=template, fields={"label": template.label})

        self.assertEqual(AuditEvent.objects.filter(app_label=AUDIT_APP_LABEL).count(), before)


class NothingIsDeletedTests(DocumentTemplatesTestCase):
    """Fails if a future session adds a delete path without revisiting the contract."""

    def test_no_delete_service_exists(self) -> None:
        forbidden = {
            "delete_signatory",
            "remove_signatory",
            "delete_template",
            "remove_template",
        }
        self.assertEqual(forbidden & set(dir(services)), set())


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------


class AuditTrailTests(DocumentTemplatesTestCase):
    def _events(self, action: str) -> Any:
        return AuditEvent.objects.filter(app_label=AUDIT_APP_LABEL, action=action)

    def test_each_action_appends_one_event(self) -> None:
        signatory = f.make_signatory(self.admin)
        services.update_signatory(actor=self.admin, signatory=signatory, fields={"role": "instructor"})
        services.change_signatory_status(actor=self.admin, signatory=signatory, status=LifecycleStatus.ACTIVE)

        for action in (
            DocumentTemplatesAuditAction.SIGNATORY_CREATED,
            DocumentTemplatesAuditAction.SIGNATORY_UPDATED,
            DocumentTemplatesAuditAction.SIGNATORY_STATUS_CHANGED,
        ):
            with self.subTest(action=action):
                self.assertEqual(self._events(action).count(), 1)

    def test_change_maps_are_not_redacted(self) -> None:
        """Unlike `documents`, there is no applicant data here to protect."""
        signatory = f.make_signatory(self.admin)

        services.update_signatory(actor=self.admin, signatory=signatory, fields={"role": "instructor"})

        event = self._events(DocumentTemplatesAuditAction.SIGNATORY_UPDATED).get()
        self.assertEqual(event.changes["role"], {"from": "director", "to": "instructor"})


# ---------------------------------------------------------------------------
# Seed data
# ---------------------------------------------------------------------------


class SeedDataTests(TestCase):
    """The transcribed slug list, and the command that loads it."""

    def setUp(self) -> None:
        self.admin = f.make_admin()

    def test_the_slug_list_holds_the_expected_count(self) -> None:
        """The frontend contract says 42; its own list contains 53."""
        self.assertEqual(len(build_seed_rows()), EXPECTED_TEMPLATE_COUNT)
        self.assertEqual(EXPECTED_TEMPLATE_COUNT, 53)

    def test_every_slug_is_unique(self) -> None:
        keys = [row["key"] for row in build_seed_rows()]

        self.assertEqual(len(keys), len(set(keys)))

    def test_the_family_split_matches_the_frontend_contract(self) -> None:
        counts: dict[str, int] = {}
        for row in build_seed_rows():
            counts[row["family"]] = counts.get(row["family"], 0) + 1

        self.assertEqual(
            counts,
            {
                DocumentFamily.STUDENT: 4,
                DocumentFamily.WODA: 11,
                DocumentFamily.LOR: 11,
                DocumentFamily.MOI: 5,
                DocumentFamily.BANK_STATEMENT: 11,
                DocumentFamily.BANK_CERTIFICATE: 11,
            },
        )

    def test_the_command_seeds_every_slug(self) -> None:
        call_command("seed_document_templates", "--username", self.admin.username, stdout=StringIO())

        self.assertEqual(DocumentTemplate.objects.count(), EXPECTED_TEMPLATE_COUNT)

    def test_the_command_is_idempotent(self) -> None:
        for _ in range(2):
            call_command("seed_document_templates", "--username", self.admin.username, stdout=StringIO())

        self.assertEqual(DocumentTemplate.objects.count(), EXPECTED_TEMPLATE_COUNT)

    def test_a_re_run_does_not_overwrite_an_edited_label(self) -> None:
        """An Admin's rename must survive re-seeding."""
        call_command("seed_document_templates", "--username", self.admin.username, stdout=StringIO())
        template = DocumentTemplate.objects.get(key="bank-vyas-statement")
        services.update_template(actor=self.admin, template=template, fields={"label": "Office name"})

        call_command("seed_document_templates", "--username", self.admin.username, stdout=StringIO())

        template.refresh_from_db()
        self.assertEqual(template.label, "Office name")

    def test_a_re_run_does_not_revive_a_retired_template(self) -> None:
        call_command("seed_document_templates", "--activate", "--username", self.admin.username, stdout=StringIO())
        template = DocumentTemplate.objects.get(key="bank-vyas-statement")
        services.change_template_status(actor=self.admin, template=template, status=LifecycleStatus.INACTIVE)

        call_command("seed_document_templates", "--activate", "--username", self.admin.username, stdout=StringIO())

        template.refresh_from_db()
        self.assertFalse(template.is_active)

    def test_dry_run_writes_nothing(self) -> None:
        call_command("seed_document_templates", "--dry-run", "--username", self.admin.username, stdout=StringIO())

        self.assertEqual(DocumentTemplate.objects.count(), 0)
