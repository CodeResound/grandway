"""Add denormalized retirement-lifecycle metadata to PolicyEndpoint.

Adds current-state fields (deprecated_at, disabled_at, sunset_at,
replaced_by_permission_key, removal_ticket, removal_reason) so audit queries are
plain field reads instead of PolicyChangeLog scans. All fields are nullable/blank
(safe on existing rows). A best-effort data migration backfills deprecated_at /
disabled_at for already-deprecated / already-disabled endpoints from the latest
matching append-only PolicyChangeLog event, falling back to the endpoint's
updated_at when no changelog row exists. The backfill only fills nulls — it never
clears existing data — and is reversible via a no-op.
"""

from django.db import migrations, models


def backfill_lifecycle_timestamps(apps, schema_editor):
    PolicyEndpoint = apps.get_model("policy_engine", "PolicyEndpoint")
    PolicyChangeLog = apps.get_model("policy_engine", "PolicyChangeLog")

    # deprecated_at from the latest DEPRECATED changelog row (fallback: updated_at).
    for endpoint in PolicyEndpoint.objects.filter(is_deprecated=True, deprecated_at__isnull=True):
        latest = (
            PolicyChangeLog.objects.filter(endpoint_id=endpoint.id, change_type="deprecated")
            .order_by("-created_at")
            .first()
        )
        endpoint.deprecated_at = latest.created_at if latest else endpoint.updated_at
        endpoint.save(update_fields=["deprecated_at"])

    # disabled_at from the latest REMOVED changelog row (fallback: updated_at).
    for endpoint in PolicyEndpoint.objects.filter(is_active=False, disabled_at__isnull=True):
        latest = (
            PolicyChangeLog.objects.filter(endpoint_id=endpoint.id, change_type="removed")
            .order_by("-created_at")
            .first()
        )
        endpoint.disabled_at = latest.created_at if latest else endpoint.updated_at
        endpoint.save(update_fields=["disabled_at"])


class Migration(migrations.Migration):
    dependencies = [
        ("policy_engine", "0005_add_changelog_git_provenance"),
    ]

    operations = [
        migrations.AddField(
            model_name="policyendpoint",
            name="deprecated_at",
            field=models.DateTimeField(
                blank=True,
                help_text="When deprecate_endpoint() last marked this endpoint deprecated (cleared on restore).",
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="policyendpoint",
            name="disabled_at",
            field=models.DateTimeField(
                blank=True,
                help_text="When disable_endpoint() last set is_active=False (cleared on restore).",
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="policyendpoint",
            name="removal_reason",
            field=models.TextField(
                blank=True,
                help_text="Why this endpoint is being retired (cleared on restore).",
            ),
        ),
        migrations.AddField(
            model_name="policyendpoint",
            name="removal_ticket",
            field=models.CharField(
                blank=True,
                help_text="External tracker reference for the removal, if a ticketing convention exists.",
                max_length=255,
            ),
        ),
        migrations.AddField(
            model_name="policyendpoint",
            name="replaced_by_permission_key",
            field=models.CharField(
                blank=True,
                help_text="permission_key of the successor endpoint, if any. Loose pointer — the successor "
                "may not be registered yet, so this is not a ForeignKey.",
                max_length=255,
            ),
        ),
        migrations.AddField(
            model_name="policyendpoint",
            name="sunset_at",
            field=models.DateTimeField(
                blank=True,
                help_text="Planned removal date announced at deprecation time (caller-provided; cleared on restore).",
                null=True,
            ),
        ),
        migrations.RunPython(backfill_lifecycle_timestamps, migrations.RunPython.noop),
    ]
