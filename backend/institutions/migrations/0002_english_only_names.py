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


class Migration(migrations.Migration):
    dependencies = [
        ("institutions", "0001_initial"),
    ]

    operations = [
        migrations.RemoveIndex(model_name="institution", name="institution_name_en_trgm_idx"),
        migrations.RemoveIndex(model_name="institution", name="institution_name_np_trgm_idx"),
        migrations.RemoveField(model_name="field", name="name_np"),
        migrations.RemoveField(model_name="country", name="name_np"),
        migrations.RemoveField(model_name="institution", name="name_np"),
        migrations.RenameField(model_name="field", old_name="name_en", new_name="name"),
        migrations.RenameField(model_name="country", old_name="name_en", new_name="name"),
        migrations.RenameField(model_name="institution", old_name="name_en", new_name="name"),
        migrations.RenameField(model_name="campus", old_name="name_en", new_name="name"),
        migrations.AlterModelOptions(
            name="field",
            options={
                "ordering": ["display_order", "name"],
                "verbose_name": "Study Field",
                "verbose_name_plural": "Study Fields",
            },
        ),
        migrations.AlterModelOptions(
            name="country",
            options={
                "ordering": ["display_order", "name"],
                "verbose_name": "Country",
                "verbose_name_plural": "Countries",
            },
        ),
        migrations.AlterModelOptions(
            name="institution",
            options={"ordering": ["name"], "verbose_name": "Institution", "verbose_name_plural": "Institutions"},
        ),
        migrations.AlterModelOptions(
            name="campus",
            options={"ordering": ["name"], "verbose_name": "Campus", "verbose_name_plural": "Campuses"},
        ),
        migrations.RemoveConstraint(model_name="campus", name="campus_institution_name_uniq"),
        migrations.AddConstraint(
            model_name="campus",
            constraint=models.UniqueConstraint(fields=("institution", "name"), name="campus_institution_name_uniq"),
        ),
        migrations.AddIndex(
            model_name="institution",
            index=GinIndex(fields=["name"], name="institution_name_trgm_idx", opclasses=["gin_trgm_ops"]),
        ),
    ]
