"""Add ``signatory`` as the sixth owner type, and widen the owner constraint.

§20 migration safety notes.

**Data impact: none.** No existing row changes. Before this migration there was
no way for a file to belong to a signatory, so there is nothing to backfill and
no default to choose.

**The constraint strictly widens.** ``uploaded_file_single_owner`` goes from a
five-way to a six-way disjunction, and every row satisfying the five-way form
satisfies the six-way one. ``AddConstraint`` therefore cannot fail on existing
data.

**Why the constraint is dropped and re-added rather than altered.**
``0001_initial`` inlines the *expanded* Q-tree rather than calling
``models._single_owner_condition()``, so the constraint does not track
``OWNER_FIELDS`` retroactively. Note that Django 5.2 also has ``AlterConstraint``,
whose ``database_forwards`` is a no-op — had the autodetector chosen it, the
five-way CHECK would have stayed on the PostgreSQL table while migration state
claimed six, and every signature upload would have failed with an
``IntegrityError`` in production while the SQLite test suite passed. It does not
choose it here, because changing ``condition`` changes a database attribute. If a
future edit to this constraint ever emits ``AlterConstraint``, that is a bug.

**Operation order is load-bearing and must not be reordered.** The constraint is
removed *before* the column is added and re-added *after*, so the CHECK never
references a column that does not exist.

**Reversible only while no row has ``signatory`` set.** The reverse drops the
column and restores the five-way CHECK. Any file owned by a signatory would then
have all five remaining owner columns NULL, fail the restored disjunction, and
abort the reverse migration mid-transaction. The rollback path for a release
containing signature files is a database snapshot restore, not
``migrate uploaded_files 0001`` — see ``GUIDE.txt`` §13.

**Locking.** ``ALTER TABLE ... ADD CONSTRAINT ... CHECK`` takes ACCESS EXCLUSIVE
and full-scans ``uploaded_files_uploadedfile`` to validate. Django does not emit
``NOT VALID`` + ``VALIDATE CONSTRAINT``. Trivial on a small table; schedule it
off-peak once the table has grown.

**New cross-app dependency.** This app now holds a ``PROTECT`` foreign key into
``document_templates``, and ``document_templates`` holds one back
(``Signatory.signature_file``, migration 0003). The two migrations depend on each
other in one direction only — 0003 lands first — so the graph stays acyclic.
Do not merge them.

**No new index.** The ``signatory`` FK gets only its implicit index, matching the
``snapshot`` precedent: a signatory holds one live signature plus a short chain
of superseded and archived predecessors.
"""

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("applicant_journeys", "0002_target_country_ref"),
        ("applicants", "0005_trigram_search_indexes"),
        ("document_history", "0001_initial"),
        ("document_templates", "0003_signatory_signature_file"),
        ("documents", "0001_initial"),
        ("offers", "0003_offer_offer_decided_at_idx"),
        ("uploaded_files", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="uploadedfile",
            name="uploaded_file_single_owner",
        ),
        migrations.AddField(
            model_name="uploadedfile",
            name="signatory",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="uploaded_files",
                to="document_templates.signatory",
            ),
        ),
        migrations.AddConstraint(
            model_name="uploadedfile",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    models.Q(
                        ("applicant__isnull", False),
                        ("document__isnull", True),
                        ("journey__isnull", True),
                        ("offer__isnull", True),
                        ("signatory__isnull", True),
                        ("snapshot__isnull", True),
                    ),
                    models.Q(
                        ("applicant__isnull", True),
                        ("document__isnull", True),
                        ("journey__isnull", False),
                        ("offer__isnull", True),
                        ("signatory__isnull", True),
                        ("snapshot__isnull", True),
                    ),
                    models.Q(
                        ("applicant__isnull", True),
                        ("document__isnull", True),
                        ("journey__isnull", True),
                        ("offer__isnull", False),
                        ("signatory__isnull", True),
                        ("snapshot__isnull", True),
                    ),
                    models.Q(
                        ("applicant__isnull", True),
                        ("document__isnull", False),
                        ("journey__isnull", True),
                        ("offer__isnull", True),
                        ("signatory__isnull", True),
                        ("snapshot__isnull", True),
                    ),
                    models.Q(
                        ("applicant__isnull", True),
                        ("document__isnull", True),
                        ("journey__isnull", True),
                        ("offer__isnull", True),
                        ("signatory__isnull", True),
                        ("snapshot__isnull", False),
                    ),
                    models.Q(
                        ("applicant__isnull", True),
                        ("document__isnull", True),
                        ("journey__isnull", True),
                        ("offer__isnull", True),
                        ("signatory__isnull", False),
                        ("snapshot__isnull", True),
                    ),
                    _connector="OR",
                ),
                name="uploaded_file_single_owner",
            ),
        ),
    ]
