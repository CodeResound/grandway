"""Enable pg_trgm and index the three lead name representations (§39.6).

``leads.selectors.search_leads`` searches ``full_name_np`` / ``full_name_en`` /
``full_name_romanized`` with OR ``icontains`` semantics — never ``__exact`` on a
Devanagari name. Plain B-tree indexes cannot serve a leading-wildcard
``LIKE '%…%'``, so each field gets a GIN trigram index; those three indexes are
what make the search selector viable at scale.

The ``pg_trgm`` extension is created here because this is the first searchable
model in the project. Reversible: the indexes drop cleanly, and the extension is
left in place on reverse (dropping it would break any other index built on it).
"""

from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.operations import TrigramExtension
from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("leads", "0001_initial"),
    ]

    operations = [
        TrigramExtension(),
        migrations.AddIndex(
            model_name="lead",
            index=GinIndex(
                fields=["full_name_np"],
                name="lead_name_np_trgm_idx",
                opclasses=["gin_trgm_ops"],
            ),
        ),
        migrations.AddIndex(
            model_name="lead",
            index=GinIndex(
                fields=["full_name_en"],
                name="lead_name_en_trgm_idx",
                opclasses=["gin_trgm_ops"],
            ),
        ),
        migrations.AddIndex(
            model_name="lead",
            index=GinIndex(
                fields=["full_name_romanized"],
                name="lead_name_rom_trgm_idx",
                opclasses=["gin_trgm_ops"],
            ),
        ),
    ]
