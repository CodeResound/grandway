"""Point a signatory at its uploaded signature image.

§20 migration safety notes.

**Data impact: none.** ``signature_file`` is nullable with no default; every
existing signatory keeps rendering from ``signature_image_url``, which is
retained and still honoured. This is an additive, non-breaking change (§29) and
a §41.1 MINOR.

**Reversible unconditionally.** Dropping a nullable FK cannot fail on any data.
The reverse leaves the ``uploaded_files`` rows in place with nothing pointing at
them; they remain owned by their signatory and remain downloadable, so no bytes
are stranded or lost. Note the asymmetry with ``uploaded_files.0002``, which is
*not* reversible once a file has a signatory owner — reverse this one first.

**``PROTECT``, matching ``checklists.ChecklistItem.evidence_file``** — the
project's other inbound reference to the file ledger. A file that is a
signatory's signature cannot be deleted out from under it. Inert in practice:
nothing in this project deletes an ``UploadedFile``.

**The ``AlterField`` on ``signature_image_url`` is help-text only.** No column
type, length, or nullability changes; it records that the field is now the
fallback rather than the only option.
"""

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("document_templates", "0002_english_only_names"),
        ("uploaded_files", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="signatory",
            name="signature_file",
            field=models.ForeignKey(
                blank=True,
                help_text="The uploaded signature image. Takes precedence over signature_image_url.",
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="signature_of",
                to="uploaded_files.uploadedfile",
            ),
        ),
        migrations.AlterField(
            model_name="signatory",
            name="signature_image_url",
            field=models.URLField(
                blank=True,
                help_text="A link to a signature image hosted elsewhere. The fallback — see docs/DATA_CONTRACT.md.",
                max_length=500,
            ),
        ),
    ]
