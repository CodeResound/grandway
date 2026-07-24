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

from django.db import migrations


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
            ("authenticate", "User", [("full_name_np", "full_name_en")]),
        ],
    )


class Migration(migrations.Migration):
    dependencies = [
        ("authenticate", "0004_alter_user_username"),
    ]

    operations = [
        migrations.RunPython(salvage, _noop),
        migrations.RemoveField(model_name="user", name="full_name_np"),
        migrations.RemoveField(model_name="user", name="full_name_romanized"),
        migrations.RenameField(model_name="user", old_name="full_name_en", new_name="full_name"),
    ]
