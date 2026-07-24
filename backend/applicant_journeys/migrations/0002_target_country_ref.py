"""Give a journey a real reference to the country catalogue.

Additive only. ``target_country`` — the free text every journey has carried
since this app shipped — is untouched, so no existing row loses information and
no response field changes shape (§22: adding optional fields is non-breaking).

The backfill is best-effort by design. It matches the typed destination against
the catalogue exactly, case-insensitively; anything it cannot match with
certainty is left null rather than guessed at, because a wrong country on a
journey is worse than no country at all — downstream, the reference is what
decides which document checklist an applicant inherits.
"""

import django.db.models.deletion
from django.db import migrations, models


def backfill_country_ref(apps, schema_editor):
    """Point each journey at the catalogue row its typed country names.

    Exact, case-insensitive match against the country's name and ``code``.
    Deliberately not fuzzy: "UK" does not become "United Kingdom" here. Those are
    resolved by hand, or by re-saving the journey with an explicit id.

    The name field is resolved by introspection rather than named directly: this
    migration predates the English-only rename (``institutions.0002``), so
    depending on the migration order at run time the historical ``Country`` may
    still carry the old ``name_en``/``name_np`` columns or the current ``name``.
    Reading whichever exists keeps a fresh ``migrate`` correct either way.
    """
    Country = apps.get_model("institutions", "Country")
    ApplicantJourney = apps.get_model("applicant_journeys", "ApplicantJourney")

    field_names = {f.name for f in Country._meta.get_fields()}
    name_fields = [f for f in ("name", "name_en", "name_np", "code") if f in field_names]

    lookup = {}
    for country in Country.objects.all():
        for field in name_fields:
            name = getattr(country, field, None)
            if name:
                lookup.setdefault(name.strip().casefold(), country.pk)

    if not lookup:
        return

    updated = []
    for journey in ApplicantJourney.objects.filter(target_country_ref__isnull=True).exclude(target_country=""):
        country_pk = lookup.get(journey.target_country.strip().casefold())
        if country_pk is not None:
            journey.target_country_ref_id = country_pk
            updated.append(journey)

    if updated:
        ApplicantJourney.objects.bulk_update(updated, ["target_country_ref"], batch_size=500)


def clear_country_ref(apps, schema_editor):
    """Reverse: drop every reference this migration could have set.

    Safe to run: the column is removed immediately afterwards, and the typed
    ``target_country`` it was derived from is still there.
    """
    ApplicantJourney = apps.get_model("applicant_journeys", "ApplicantJourney")
    ApplicantJourney.objects.update(target_country_ref=None)


class Migration(migrations.Migration):
    dependencies = [
        ("applicant_journeys", "0001_initial"),
        ("institutions", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="applicantjourney",
            name="target_country_ref",
            field=models.ForeignKey(
                blank=True,
                help_text=(
                    "The catalogue country this journey targets. Setting it is what makes the destination "
                    "machine-readable — and what triggers checklist inheritance in the checklists app."
                ),
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="journeys",
                to="institutions.country",
            ),
        ),
        migrations.RunPython(backfill_country_ref, clear_country_ref),
    ]
