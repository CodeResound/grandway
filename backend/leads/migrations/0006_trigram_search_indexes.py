"""Trigram-index the lead contact number for substring search (§20, §39.6).

The mirror of ``applicants/migrations/0005_trigram_search_indexes.py``, and the
correction to this app's own ``0004_search_indexes``. That migration added a
B-tree on ``number`` and reasoned correctly that the ``(lead, number)`` unique
constraint cannot serve a lookup that knows only the number — but the lookup
``search_leads`` actually issues is ``number__icontains``, whose leading
wildcard no B-tree can serve either. Every phone search was a sequential scan.

This matters more here than in ``applicants``: a lead is very often a number in
a call log before anyone has agreed how to spell the name, so the phone column
is the primary way a lead is found rather than a secondary one.

The B-tree from ``0004`` is kept — it stays cheaper for exact-match paths.

Data impact: none. Reversible: the index drops cleanly. Rollback is
``migrate leads 0005``.

Lock note: ``CREATE INDEX`` takes a ``SHARE`` lock, blocking writes to
``leads_leadcontactnumber`` while it builds — seconds at this project's scale.
Switch to ``AddIndexConcurrently`` with ``atomic = False`` if that ever stops
being true.
"""

import django.contrib.postgres.indexes
from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("leads", "0005_english_only_names"),
    ]

    operations = [
        migrations.AddIndex(
            model_name="leadcontactnumber",
            index=django.contrib.postgres.indexes.GinIndex(
                fields=["number"], name="lead_contact_num_trgm_idx", opclasses=["gin_trgm_ops"]
            ),
        ),
    ]
