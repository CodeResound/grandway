"""Give existing journeys the checklist their destination now has.

Automatic inheritance (``checklists/signals.py``) fires when a journey is saved.
That leaves three populations it cannot reach, and this command is the answer to
all three:

* journeys that named their country **before** anyone authored that country's
  template — the common case, since the catalogue is filled in over time
* journeys written by a bulk import that ran with ``DISABLE_SIGNALS`` (§11)
* journeys whose inheritance failed once and was logged rather than retried

It never re-creates a checklist that already exists, and never touches one that
does — the same idempotency check the signal uses, so running it twice is a
no-op and running it on a live system is safe.
"""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from checklists.selectors import get_default_template_for_country, get_live_checklist_from_template
from checklists.services import inherit_for_journey


class Command(BaseCommand):
    help = "Apply each country's default checklist to journeys that name that country but hold no checklist."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--country",
            dest="country_id",
            help="Restrict to one catalogue country id. Omit to sweep every country.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would be created and write nothing.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            help="Stop after this many journeys. Useful for a first cautious pass on a large database.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        from applicant_journeys.models import ApplicantJourney

        dry_run: bool = options["dry_run"]
        country_id: str | None = options.get("country_id")
        limit: int | None = options.get("limit")

        journeys = ApplicantJourney.objects.select_related("applicant", "target_country_ref").filter(
            target_country_ref__isnull=False
        )
        if country_id:
            journeys = journeys.filter(target_country_ref_id=country_id)
            if not journeys.exists():
                # Not an error worth failing on if the country simply has no
                # journeys — but a mistyped id should not report "0 created" and
                # look like success.
                if not get_default_template_for_country(country_id):
                    raise CommandError(f"No active default checklist template for country {country_id}.")
        journeys = journeys.order_by("created_at")

        created = 0
        skipped_no_template = 0
        skipped_existing = 0
        failed = 0
        examined = 0

        for journey in journeys.iterator():
            if limit is not None and examined >= limit:
                break
            examined += 1

            template = get_default_template_for_country(journey.target_country_ref_id)
            if template is None:
                skipped_no_template += 1
                continue
            if get_live_checklist_from_template(journey.pk, template.pk) is not None:
                skipped_existing += 1
                continue

            if dry_run:
                created += 1
                self.stdout.write(
                    f"  would apply '{template.label}' to {journey.applicant.full_name_np} ({journey.pk})"
                )
                continue

            try:
                with transaction.atomic():
                    inherit_for_journey(journey)
            except Exception as exc:  # noqa: BLE001 — one bad journey must not stop the sweep.
                failed += 1
                self.stderr.write(self.style.WARNING(f"  {journey.pk}: {exc}"))
                continue
            created += 1

        verb = "would create" if dry_run else "created"
        self.stdout.write(
            self.style.SUCCESS(
                f"Examined {examined} journey(s): {verb} {created}, "
                f"{skipped_existing} already had one, {skipped_no_template} had no template for their country"
                + (f", {failed} failed" if failed else "")
            )
        )
        if skipped_no_template:
            self.stdout.write(
                "Journeys with no template for their country are listed by "
                "GET /api/v1/checklists/?journey_missing_checklist=true"
            )
