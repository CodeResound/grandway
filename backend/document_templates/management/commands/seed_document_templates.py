"""Populate the template catalogue from the transcribed frontend slug list."""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from documents.services import assert_template_key_matches_family

from document_templates.constants import LifecycleStatus
from document_templates.models import DocumentTemplate
from document_templates.seed_data import EXPECTED_TEMPLATE_COUNT, build_seed_rows


class Command(BaseCommand):
    """Seed the document template catalogue.

    Creates one catalogue row per template slug listed in
    ``document_templates/seed_data.py``, which is transcribed from the
    frontend's own contract. Idempotent: an existing row is left **completely
    untouched**, including its label, description, display order, and status.
    That is deliberate — an Admin who renamed "Vyas Statement" to something the
    office actually says should not have it reverted by a re-run, and a template
    someone retired should not come back.

    Requires an actor to attribute the rows to, because ``created_by`` is a
    non-null ``PROTECT`` foreign key. Defaults to the first superadmin.

    Flags:
      --dry-run    Report what would be created; write nothing.
      --activate   Create rows as ``active`` rather than ``draft``, so the
                   picker is usable immediately.
      --username   Attribute created rows to this user instead of the first
                   superadmin found.
    """

    help = "Seed the document template catalogue from the transcribed frontend slug list."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would be created without writing anything.",
        )
        parser.add_argument(
            "--activate",
            action="store_true",
            help="Create rows as active rather than draft.",
        )
        parser.add_argument(
            "--username",
            type=str,
            default=None,
            help="Attribute created rows to this user. Defaults to the first superadmin.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        dry_run: bool = options["dry_run"]
        status = LifecycleStatus.ACTIVE if options["activate"] else LifecycleStatus.DRAFT

        rows = build_seed_rows()
        if len(rows) != EXPECTED_TEMPLATE_COUNT:
            raise CommandError(
                f"seed_data produced {len(rows)} rows, expected {EXPECTED_TEMPLATE_COUNT}. "
                f"The slug list has been edited without updating EXPECTED_TEMPLATE_COUNT."
            )

        # Fail before writing anything if any transcribed slug disagrees with
        # its family under the rule ``documents`` enforces. A catalogue row no
        # document could be created from is worse than a missing one.
        for row in rows:
            assert_template_key_matches_family(row["family"], row["key"])

        actor = self._resolve_actor(options["username"])
        existing = set(DocumentTemplate.objects.values_list("key", flat=True))
        missing = [row for row in rows if row["key"] not in existing]

        if dry_run:
            self.stdout.write(
                f"[dry-run] {len(missing)} template(s) would be created as '{status}'; "
                f"{len(rows) - len(missing)} already exist and would be left untouched."
            )
            for row in missing:
                self.stdout.write(f"  + {row['key']}  ({row['family']})  {row['label']}")
            return

        with transaction.atomic():
            DocumentTemplate.objects.bulk_create(
                [
                    DocumentTemplate(
                        key=row["key"],
                        family=row["family"],
                        label=row["label"],
                        display_order=row["display_order"],
                        status=status,
                        created_by=actor,
                    )
                    for row in missing
                ]
            )

        self.stdout.write(
            self.style.SUCCESS(
                f"Seeded {len(missing)} template(s) as '{status}'; "
                f"{len(rows) - len(missing)} already existed and were left untouched. "
                f"Catalogue now holds {DocumentTemplate.objects.count()} row(s)."
            )
        )

    def _resolve_actor(self, username: str | None) -> Any:
        """The user to attribute created rows to.

        Imported inside the method rather than at module scope so the command
        module stays importable before the app registry is ready.
        """
        from authenticate.constants import AuthorityType
        from authenticate.models import User

        if username:
            actor = User.objects.filter(username=username).first()
            if actor is None:
                raise CommandError(f"No user with username '{username}'.")
            return actor

        actor = User.objects.filter(authority_type=AuthorityType.SUPERADMIN).order_by("created_at").first()
        if actor is None:
            raise CommandError(
                "No superadmin found to attribute templates to. "
                "Run `python manage.py bootstrap_superadmin` first, or pass --username."
            )
        return actor
