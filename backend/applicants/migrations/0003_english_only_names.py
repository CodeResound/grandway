"""English-only names: drop the `_np`/`_romanized` columns, rename `_en` to bare.

The project is English-only. The bilingual `_np`/`_en`/`_romanized` triple
(CLAUDE.md §39.1 as it stood) modelled two canonical identities for one record;
with one language there is one name, and a `_en` suffix distinguishes nothing.

**Destructive.** The `_np` and `_romanized` columns are dropped and cannot be
recovered by reversing this migration — the reverse re-creates the columns
empty. The `RunPython` step below runs first and copies a `_np` value into the
surviving column wherever that column is blank, so a record whose only name was
Devanagari keeps a name rather than becoming nameless. Names already in English
are untouched.

Renames (not drop+add) carry the existing column data across.
"""

from django.contrib.postgres.indexes import GinIndex
from django.db import migrations, models


def _salvage(apps, schema_editor, model_paths):
    """Copy `<f>_np` into `<f>_en` wherever `<f>_en` is blank, before the drop."""
    for app_label, model_name, pairs in model_paths:
        Model = apps.get_model(app_label, model_name)
        for np_field, en_field in pairs:
            for row in Model.objects.filter(**{f"{en_field}": ""}).exclude(**{f"{np_field}": ""}):
                setattr(row, en_field, getattr(row, np_field))
                row.save(update_fields=[en_field])


def _noop(apps, schema_editor):
    """Reverse is a no-op: the dropped columns are re-created empty."""


def salvage(apps, schema_editor):
    _salvage(
        apps,
        schema_editor,
        [
            ("applicants", "Applicant", [("full_name_np", "full_name_en")]),
            ("applicants", "FamilyMember", [("full_name_np", "full_name_en")]),
            ("applicants", "EmergencyContact", [("full_name_np", "full_name_en")]),
        ],
    )


class Migration(migrations.Migration):
    dependencies = [
        ("applicants", "0002_search_indexes"),
    ]

    operations = [
        migrations.RunPython(salvage, _noop),
        migrations.RemoveIndex(model_name="applicant", name="appl_name_np_trgm_idx"),
        migrations.RemoveIndex(model_name="applicant", name="appl_name_en_trgm_idx"),
        migrations.RemoveIndex(model_name="applicant", name="appl_name_rom_trgm_idx"),
        migrations.RemoveField(model_name="applicant", name="full_name_np"),
        migrations.RemoveField(model_name="applicant", name="full_name_romanized"),
        migrations.RemoveField(model_name="familymember", name="full_name_np"),
        migrations.RemoveField(model_name="emergencycontact", name="full_name_np"),
        migrations.RenameField(model_name="applicant", old_name="full_name_en", new_name="full_name"),
        migrations.RenameField(model_name="familymember", old_name="full_name_en", new_name="full_name"),
        migrations.RenameField(model_name="emergencycontact", old_name="full_name_en", new_name="full_name"),
        migrations.AlterField(model_name="applicant", name="full_name", field=models.CharField(max_length=255)),
        migrations.AlterField(model_name="familymember", name="full_name", field=models.CharField(max_length=255)),
        migrations.AlterField(model_name="emergencycontact", name="full_name", field=models.CharField(max_length=255)),
        migrations.AddIndex(
            model_name="applicant",
            index=GinIndex(fields=["full_name"], name="appl_name_trgm_idx", opclasses=["gin_trgm_ops"]),
        ),
    ]
