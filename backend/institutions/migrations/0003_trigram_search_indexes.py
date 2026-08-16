"""Trigram-index the institution's informal name (§20, §39.6).

``filter_institutions`` matches ``name`` **or** ``common_name`` in one ``Q``.
Only ``name`` was indexed, which meant the unindexed half decided the cost of
the whole query — PostgreSQL cannot use the trigram index on ``name`` to satisfy
a disjunction whose other branch requires a scan, so the pair behaved as if
neither were indexed.

``common_name`` is also the one staff are more likely to type: it exists
precisely to hold what people actually call the place ("Unimelb"), which is what
someone types into a search box rather than the registered legal name.

Data impact: none. Reversible: the index drops cleanly. Rollback is
``migrate institutions 0002``.

Lock note: ``CREATE INDEX`` takes a ``SHARE`` lock on
``institutions_institution`` while it builds. The catalogue is a small table;
this is not a concern at any foreseeable scale.
"""

import django.contrib.postgres.indexes
from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("institutions", "0002_english_only_names"),
    ]

    operations = [
        migrations.AddIndex(
            model_name="institution",
            index=django.contrib.postgres.indexes.GinIndex(
                fields=["common_name"], name="institution_common_trgm_idx", opclasses=["gin_trgm_ops"]
            ),
        ),
    ]
