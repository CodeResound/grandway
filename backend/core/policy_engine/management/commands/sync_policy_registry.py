"""
Management command: sync_policy_registry

Discovers all POLICY_ENDPOINTS lists from installed apps' registry.py files
and syncs them into the database. Idempotent — safe to run multiple times.

Usage:
    python manage.py sync_policy_registry
    python manage.py sync_policy_registry --dry-run   # show what would change
    python manage.py sync_policy_registry --by ai --identifier "claude-sonnet"
"""

from django.core.management.base import BaseCommand

from core.policy_engine.constants import CreatedByType
from core.policy_engine.registry import load_registry_configs_from_installed_apps, register_from_config
from core.policy_engine.validators import validate_registry_config


class Command(BaseCommand):
    help = "Sync declared POLICY_ENDPOINTS configs from all installed apps into the database."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            default=False,
            help="Print what would be synced without writing to the database.",
        )
        parser.add_argument(
            "--by",
            default=CreatedByType.SYSTEM,
            choices=[CreatedByType.HUMAN, CreatedByType.AI, CreatedByType.SYSTEM],
            help="Type of author running the sync (default: system).",
        )
        parser.add_argument(
            "--identifier",
            default="sync_policy_registry",
            help="Identifier of the author running the sync.",
        )

    def handle(self, *args, **options):
        dry_run: bool = options["dry_run"]
        created_by_type: str = options["by"]
        created_by_identifier: str = options["identifier"]

        configs = load_registry_configs_from_installed_apps()

        if not configs:
            self.stdout.write(self.style.WARNING("No POLICY_ENDPOINTS declarations found in installed apps."))
            return

        self.stdout.write(f"Found {len(configs)} endpoint config(s) to sync.")

        # Schema-validate every config before any lifecycle write so one bad
        # declaration fails the whole sync early with every problem listed,
        # instead of failing opaquely mid-lifecycle.
        config_problems: list[str] = []
        for config in configs:
            problems = validate_registry_config(config)
            if problems:
                label = config.get("permission_key") or config.get("endpoint_key") or "<unidentified config>"
                config_problems.extend(f"[{label}] {problem}" for problem in problems)

        if config_problems:
            for problem in config_problems:
                self.stderr.write(self.style.ERROR(f"  ✗ Invalid config: {problem}"))
            self.stderr.write(
                self.style.ERROR(
                    f"\nRegistry validation failed: {len(config_problems)} problem(s) found. "
                    "No policy engine records were written."
                )
            )
            raise SystemExit(1)

        if dry_run:
            self.stdout.write(self.style.WARNING("[DRY RUN] The following configs would be synced:"))
            for config in configs:
                self.stdout.write(f"  - {config.get('permission_key', '?')} ({config.get('operation_type', '?')})")
            return

        success_count = 0
        error_count = 0

        for config in configs:
            permission_key = config.get("permission_key", "?")
            try:
                result = register_from_config(
                    config=config,
                    created_by_type=created_by_type,
                    created_by_identifier=created_by_identifier,
                )
                if result.get("errors"):
                    for err in result["errors"]:
                        self.stderr.write(self.style.WARNING(f"  WARN [{permission_key}]: {err}"))
                self.stdout.write(self.style.SUCCESS(f"  ✓ Synced: {permission_key}"))
                success_count += 1
            except Exception as exc:  # noqa: BLE001
                self.stderr.write(self.style.ERROR(f"  ✗ Failed: {permission_key} — {exc}"))
                error_count += 1

        self.stdout.write(f"\nSync complete: {success_count} succeeded, {error_count} failed.")
