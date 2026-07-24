"""Index ``AuditEvent.summary`` for the audit log's free-text search (§39.6).

``audit.selectors.get_events`` gained a ``search`` filter that runs
``summary__icontains`` — a leading-wildcard ``LIKE``, which no B-tree index can
serve. The GIN trigram index below is what makes that filter viable once the
audit table is large, which it always eventually is: audit rows are append-only
and never deleted.

``TrigramExtension()`` is idempotent and already created by earlier apps'
migrations; it is repeated here so this app's migration graph does not depend on
another app happening to run first. Reversible: the index drops cleanly and the
extension is deliberately left in place on reverse (dropping it would break
every other trigram index in the project).
"""

from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.operations import TrigramExtension
from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("audit", "0001_initial"),
    ]

    operations = [
        TrigramExtension(),
        migrations.AddIndex(
            model_name="auditevent",
            index=GinIndex(
                fields=["summary"],
                name="audit_summary_trgm_idx",
                opclasses=["gin_trgm_ops"],
            ),
        ),
    ]
