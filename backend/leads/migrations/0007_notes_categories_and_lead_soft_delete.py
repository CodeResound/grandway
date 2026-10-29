# Lead soft delete, and categorised, backdatable, correctable notes
# (frontend updates.md §2, §3.1 — 2026-10-29).
#
# Lead: deleted_at (indexed — every lead list filters on it), deleted_by,
#   delete_reason. All nullable/blank: no existing lead is deleted.
# LeadNote: category (existing rows -> "general"), noted_at, updated_by,
#   deleted_at, deleted_by, and an (lead, -noted_at) index for the notes panel,
#   which now orders by noted_at.
#
# noted_at is the one data step. It is added nullable, backfilled from
# created_at — an existing note was written when it was saved, so it is not
# backdated — and only then made NOT NULL. Reversing removes the columns; the
# backfill's reverse is a no-op because the column is dropped anyway.
#
# Non-destructive: no column is dropped or retyped, and no row is deleted.

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models
from django.db.models import F


def backfill_noted_at(apps, schema_editor):
    LeadNote = apps.get_model("leads", "LeadNote")
    LeadNote.objects.filter(noted_at__isnull=True).update(noted_at=F("created_at"))


class Migration(migrations.Migration):
    dependencies = [
        ("leads", "0006_trigram_search_indexes"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="lead",
            name="deleted_at",
            field=models.DateTimeField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name="lead",
            name="deleted_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="leads_deleted",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="lead",
            name="delete_reason",
            field=models.CharField(blank=True, max_length=500),
        ),
        migrations.AddField(
            model_name="leadnote",
            name="category",
            field=models.CharField(
                choices=[("general", "General"), ("visit", "Visit")], default="general", max_length=20
            ),
        ),
        migrations.AddField(
            model_name="leadnote",
            name="noted_at",
            field=models.DateTimeField(db_index=True, null=True),
        ),
        migrations.RunPython(backfill_noted_at, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="leadnote",
            name="noted_at",
            field=models.DateTimeField(db_index=True),
        ),
        migrations.AddField(
            model_name="leadnote",
            name="updated_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="lead_notes_updated",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="leadnote",
            name="deleted_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="leadnote",
            name="deleted_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="lead_notes_deleted",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AlterModelOptions(
            name="leadnote",
            options={
                "ordering": ["-noted_at", "-created_at"],
                "verbose_name": "Lead Note",
                "verbose_name_plural": "Lead Notes",
            },
        ),
        migrations.AddIndex(
            model_name="leadnote",
            index=models.Index(fields=["lead", "-noted_at"], name="leadnote_lead_noted_idx"),
        ),
    ]
