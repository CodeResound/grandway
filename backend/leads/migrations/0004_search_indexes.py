"""Index the two fields ``search_leads`` gained beyond the name (§20, §39.6).

The mirror of ``applicants/migrations/0002_search_indexes.py``, for the same
reason and against the same query. Phone and email matter more here than
anywhere else in the project: a lead is very often a number in a call log before
anyone has agreed how to spell the name.

* ``email`` — matched with a leading wildcard (``icontains``), which a B-tree
  index cannot serve, so it gets the same GIN trigram treatment as the three
  name representations. ``pg_trgm`` is already enabled by ``0002``.
* ``LeadContactNumber.number`` — the only existing index on this column is the
  ``(lead, number)`` unique constraint, whose leading column is the lead. A
  search that knows the number and not the lead cannot use it.

Purely additive and fully reversible: the indexes drop cleanly and no column,
constraint, or row is touched.
"""

import django.contrib.postgres.indexes
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("applicant_journeys", "0002_target_country_ref"),
        ("applicants", "0002_search_indexes"),
        ("leads", "0003_lead_converted_applicant_lead_converted_journey"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddIndex(
            model_name="lead",
            index=django.contrib.postgres.indexes.GinIndex(
                fields=["email"], name="lead_email_trgm_idx", opclasses=["gin_trgm_ops"]
            ),
        ),
        migrations.AddIndex(
            model_name="leadcontactnumber",
            index=models.Index(fields=["number"], name="lead_contact_number_idx"),
        ),
    ]
