"""Trigram-index the two fields a substring search could not reach (§20, §39.6).

``0002_search_indexes`` indexed ``email`` with GIN trigram but left the contact
number and the passport number on plain B-trees. That was half right: both
columns are matched with ``icontains``, which has a leading wildcard, and a
B-tree cannot serve a leading wildcard at all. The two most physical ways staff
identify a person — a number read off a call log, the last digits of the
passport in front of them — were each a sequential scan.

The existing B-tree indexes are **kept**, not replaced: they remain the cheaper
structure for the equality and prefix lookups elsewhere in the app, and dropping
them to save space would trade a real index for a hypothetical saving.

Both columns are short (32 and 50 characters), so the trigram indexes are small
relative to the tables they cover.

Data impact: none — no column, constraint, or row is touched. Reversible: the
indexes drop cleanly. Rollback is ``migrate applicants 0004``.

Lock note: ``CREATE INDEX`` takes a ``SHARE`` lock, blocking writes to these two
tables while it builds. At this project's scale that is seconds. If either table
ever grows past the point where that is acceptable, switch to
``AddIndexConcurrently`` with ``atomic = False``.
"""

import django.contrib.postgres.indexes
from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("applicants", "0004_alter_emergencycontact_full_name_and_more"),
    ]

    operations = [
        migrations.AddIndex(
            model_name="applicantcontactnumber",
            index=django.contrib.postgres.indexes.GinIndex(
                fields=["number"], name="appl_contact_num_trgm_idx", opclasses=["gin_trgm_ops"]
            ),
        ),
        migrations.AddIndex(
            model_name="passportdetail",
            index=django.contrib.postgres.indexes.GinIndex(
                fields=["passport_number"], name="appl_passport_num_trgm_idx", opclasses=["gin_trgm_ops"]
            ),
        ),
    ]
