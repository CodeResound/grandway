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
            ("clients", "Client", [("name_np", "name_en"), ("spokesperson_name_np", "spokesperson_name_en")]),
        ],
    )


class Migration(migrations.Migration):
    dependencies = [
        ("clients", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(salvage, _noop),
        migrations.RemoveIndex(model_name="client", name="client_status_name_idx"),
        migrations.RemoveIndex(model_name="client", name="client_name_np_trgm_idx"),
        migrations.RemoveIndex(model_name="client", name="client_name_en_trgm_idx"),
        migrations.RemoveIndex(model_name="client", name="client_name_rom_trgm_idx"),
        migrations.RemoveField(model_name="client", name="name_np"),
        migrations.RemoveField(model_name="client", name="name_romanized"),
        migrations.RemoveField(model_name="client", name="spokesperson_name_np"),
        migrations.RemoveField(model_name="client", name="spokesperson_name_romanized"),
        migrations.RenameField(model_name="client", old_name="name_en", new_name="name"),
        migrations.RenameField(model_name="client", old_name="spokesperson_name_en", new_name="spokesperson_name"),
        migrations.AlterField(model_name="client", name="name", field=models.CharField(max_length=255)),
        migrations.AlterModelOptions(
            name="client",
            options={"ordering": ["name"], "verbose_name": "Client", "verbose_name_plural": "Clients"},
        ),
        migrations.AddIndex(
            model_name="client",
            index=models.Index(fields=["status", "name"], name="client_status_name_idx"),
        ),
        migrations.AddIndex(
            model_name="client",
            index=GinIndex(fields=["name"], name="client_name_trgm_idx", opclasses=["gin_trgm_ops"]),
        ),
    ]
