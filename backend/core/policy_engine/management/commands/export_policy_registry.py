"""
Management command: export_policy_registry

Emits machine-readable artifacts derived from the Core Policy Engine registry
(the declarative `POLICY_ENDPOINTS` across all apps):

    --format registry   canonical registry JSON (default)
    --format openapi     OpenAPI 3.1 document

Both are pure functions of the registry declarations (no database), so the output
is deterministic and diff-stable. The committed artifacts live under
`core/policy_engine/docs/` and are kept fresh in CI via `--check`, which
regenerates in-memory and fails (exit 1) if the committed file has drifted —
mirroring `manage.py makemigrations --check`.

Usage:
    python manage.py export_policy_registry                      # registry JSON -> stdout
    python manage.py export_policy_registry --format openapi     # OpenAPI -> stdout
    python manage.py export_policy_registry --format registry --output <path>
    python manage.py export_policy_registry --format openapi --check
"""

import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from core.policy_engine.exporters import build_openapi_document, build_registry_export

_DOCS_DIR = Path(__file__).resolve().parents[2] / "docs"
_COMMITTED_ARTIFACT = {
    "registry": _DOCS_DIR / "registry_export.json",
    "openapi": _DOCS_DIR / "openapi.json",
}


def _render(fmt: str) -> str:
    document = build_registry_export() if fmt == "registry" else build_openapi_document()
    # Trailing newline keeps the committed file POSIX-clean and diff-stable.
    return json.dumps(document, indent=2, ensure_ascii=False, sort_keys=False) + "\n"


class Command(BaseCommand):
    help = "Export the policy registry as canonical JSON or an OpenAPI 3.1 document."

    def add_arguments(self, parser):
        parser.add_argument(
            "--format",
            choices=["registry", "openapi"],
            default="registry",
            help="Artifact to emit (default: registry).",
        )
        parser.add_argument(
            "--output",
            default="",
            help="Write to this file path instead of stdout.",
        )
        parser.add_argument(
            "--check",
            action="store_true",
            default=False,
            help="Compare freshly-generated output against the committed artifact; exit 1 on drift.",
        )

    def handle(self, *args, **options):
        fmt = options["format"]
        content = _render(fmt)

        if options["check"]:
            committed = _COMMITTED_ARTIFACT[fmt]
            if not committed.exists():
                raise CommandError(
                    f"Committed artifact '{committed}' does not exist. "
                    f"Generate it: python manage.py export_policy_registry --format {fmt} --output {committed}"
                )
            existing = committed.read_text(encoding="utf-8")
            if existing != content:
                raise CommandError(
                    f"'{committed}' is stale — the registry changed but the committed artifact was not "
                    f"regenerated. Run: python manage.py export_policy_registry --format {fmt} --output {committed}"
                )
            self.stdout.write(self.style.SUCCESS(f"{fmt} artifact is up to date."))
            return

        if options["output"]:
            path = Path(options["output"])
            path.write_text(content, encoding="utf-8")
            self.stdout.write(self.style.SUCCESS(f"Wrote {fmt} artifact to {path}."))
        else:
            # Raw document to stdout (no trailing style formatting) for piping.
            self.stdout.write(content, ending="")
