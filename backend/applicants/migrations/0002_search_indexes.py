"""Index the three fields ``search_applicants`` gained beyond the name (§20, §39.6).

The applicant search used to match names only. It now also matches email,
contact number, and passport number, because that is how staff actually find a
file: a number read off a call log, an email from an enquiry, the passport in
front of them. Each of those three lookups needs an index it did not have.

* ``email`` — matched with a leading wildcard (``icontains``), which a B-tree
  index cannot serve, so it gets the same GIN trigram treatment as the three
  name representations. ``pg_trgm`` is already enabled by ``0001_initial``.
* ``ApplicantContactNumber.number`` — the model's only existing index on this
  column is the ``(applicant, number)`` unique constraint, whose leading column
  is the applicant. A search that knows the number and not the person cannot
  use it.
* ``PassportDetail.passport_number`` — same situation, with no covering index at
  all before this.

Purely additive and fully reversible: the indexes drop cleanly and no column,
constraint, or row is touched.
"""

import django.contrib.postgres.indexes
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("applicants", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddIndex(
            model_name="applicant",
            index=django.contrib.postgres.indexes.GinIndex(
                fields=["email"], name="appl_email_trgm_idx", opclasses=["gin_trgm_ops"]
            ),
        ),
        migrations.AddIndex(
            model_name="applicantcontactnumber",
            index=models.Index(fields=["number"], name="appl_contact_number_idx"),
        ),
        migrations.AddIndex(
            model_name="passportdetail",
            index=models.Index(fields=["passport_number"], name="appl_passport_number_idx"),
        ),
    ]
