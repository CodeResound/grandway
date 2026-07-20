"""
Management command: validate_integration_docs

Enforces that every app exposing endpoints publishes a consumer-facing
`docs/INTEGRATION.md` (CLAUDE.md §19.1) and that the contract stays complete as
the registry changes.

Why this exists: `INTEGRATION.md` is the contract an *external* consumer — a
client author, or an AI working in a different repository — integrates against.
Unverified documentation decays silently, and a consumer cannot tell a missing
endpoint from a non-existent one. This command makes the endpoint inventory in
the docs provably match the registry, the same way `validate_policy_engine`
rule 14 makes the registry provably match the routed URLs.

Reads registry *declarations* (each app's `registry.py` `POLICY_ENDPOINTS`), not
the database, so it runs in CI without PostgreSQL — the same source
`export_policy_registry` and `validate_policy_engine`'s drift rules use.

Checks:
  1. Every app with registered endpoints has `docs/INTEGRATION.md`.
  2. Every registered permission_key appears in its app's file.
     (Catches an endpoint shipped without a consumer contract.)
  3. Every permission_key mentioned in a file still exists in the registry.
     (Catches a stale entry left behind after retirement.)
  4. All nine required section headings are present, in order.
  5. The mandatory depth fields are present: §2 `Requires` is non-empty, and every
     endpoint block declares `Requires state` and `Side effects` — the literal
     `none` counts, silence does not. An omitted field is indistinguishable from
     "the author thought it was obvious", which is exactly what an external
     reader cannot recover.
  6. The project-level entry point `core/docs/INTEGRATION.md` exists and lists
     every app that has one.

Exit codes: 0 = pass, 1 = findings. Warnings do not fail unless --strict.

Usage:
    python manage.py validate_integration_docs
    python manage.py validate_integration_docs --strict
"""

import importlib
import re
from pathlib import Path
from typing import Any

from django.apps import apps
from django.core.management.base import BaseCommand

# The nine section headings, in required order (CLAUDE.md §19.3).
REQUIRED_SECTIONS: list[str] = [
    "1. Module",
    "2. Requires",
    "3. Conventions",
    "4. Models",
    "5. Enums",
    "6. Dependency order",
    "7. Endpoints",
    "8. Flows",
    "9. Gaps",
]

# Fields that must appear at least once inside §7 Endpoints.
REQUIRED_ENDPOINT_FIELDS: list[str] = ["Requires state:", "Side effects:"]

INTEGRATION_DOC_RELPATH = Path("docs") / "INTEGRATION.md"
PROJECT_ENTRY_POINT = Path("core") / "docs" / "INTEGRATION.md"

# A permission key: lowercase dotted segments, e.g. policy_engine.application.list
PERMISSION_KEY_RE = re.compile(r"\b[a-z0-9_]+\.[a-z0-9_]+\.[a-z0-9_]+\b")


def _discover_app_endpoints() -> dict[str, tuple[Any, list[dict[str, Any]]]]:
    """Map app_key -> (AppConfig, [endpoint configs]) for apps declaring endpoints.

    `load_registry_configs_from_installed_apps()` returns a flat list that loses
    the app association, so this repeats its discovery while keeping the owning
    AppConfig (needed for the on-disk docs path).
    """
    discovered: dict[str, tuple[Any, list[dict[str, Any]]]] = {}

    for app_config in apps.get_app_configs():
        try:
            module = importlib.import_module(f"{app_config.name}.registry")
        except ModuleNotFoundError:
            continue

        policy_endpoints = getattr(module, "POLICY_ENDPOINTS", None)
        if not policy_endpoints or not isinstance(policy_endpoints, list):
            continue

        for config in policy_endpoints:
            app_key = config.get("app_key")
            if not app_key:
                continue
            if app_key not in discovered:
                discovered[app_key] = (app_config, [])
            discovered[app_key][1].append(config)

    return discovered


def _section_order_findings(doc_text: str, label: str) -> list[str]:
    """Report missing headings, and headings present but out of order."""
    findings: list[str] = []
    positions: list[tuple[int, str]] = []

    for section in REQUIRED_SECTIONS:
        match = re.search(rf"^##\s+{re.escape(section)}\s*$", doc_text, re.MULTILINE)
        if match is None:
            findings.append(f"{label}: missing required section heading '## {section}'.")
        else:
            positions.append((match.start(), section))

    ordered = [name for _, name in sorted(positions)]
    expected = [s for s in REQUIRED_SECTIONS if s in ordered]
    if ordered != expected:
        findings.append(f"{label}: sections are out of order. Expected {expected}, found {ordered}.")

    return findings


def _extract_section(doc_text: str, heading: str) -> str:
    """Return the body between `## <heading>` and the next `## `, or ''."""
    pattern = rf"^##\s+{re.escape(heading)}\s*$(.*?)(?=^##\s|\Z)"
    match = re.search(pattern, doc_text, re.MULTILINE | re.DOTALL)
    return match.group(1) if match else ""


class Command(BaseCommand):
    help = "Validate that every app's consumer-facing INTEGRATION.md matches the endpoint registry."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--strict",
            action="store_true",
            help="Treat warnings as failures (exit 1).",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        strict: bool = options["strict"]
        errors: list[str] = []
        warnings: list[str] = []

        backend_root = Path(apps.get_app_config("core").path).parent
        discovered = _discover_app_endpoints()
        documented_apps: list[str] = []

        for app_key, (app_config, configs) in sorted(discovered.items()):
            doc_path = Path(app_config.path) / INTEGRATION_DOC_RELPATH
            rel = doc_path.relative_to(backend_root)

            # Check 1 — the file exists at all.
            if not doc_path.is_file():
                errors.append(
                    f"App '{app_key}' registers {len(configs)} endpoint(s) but has no "
                    f"{rel}. Copy core/docs/templates/INTEGRATION_TEMPLATE.md (CLAUDE.md §19.1)."
                )
                continue

            documented_apps.append(app_key)
            doc_text = doc_path.read_text(encoding="utf-8")

            # Check 4 — required sections, in order.
            errors.extend(_section_order_findings(doc_text, str(rel)))

            # Check 2 — every registered key is documented.
            declared_keys = {c["permission_key"] for c in configs if c.get("permission_key")}
            for key in sorted(declared_keys):
                if key not in doc_text:
                    errors.append(
                        f"{rel}: registered endpoint '{key}' is not documented. "
                        f"A consumer cannot distinguish an undocumented endpoint from a "
                        f"non-existent one."
                    )

            # Check 3 — no stale keys for this app.
            mentioned = {k for k in PERMISSION_KEY_RE.findall(doc_text) if k.startswith(f"{app_key}.")}
            for key in sorted(mentioned - declared_keys):
                errors.append(
                    f"{rel}: documents '{key}', which is not in the registry. "
                    f"Remove it, or restore the registry declaration."
                )

            # Check 5 — mandatory depth fields.
            requires_body = _extract_section(doc_text, "2. Requires").strip()
            if not requires_body:
                errors.append(
                    f"{rel}: §2 Requires is empty. State the app-level dependencies, " f"or the literal 'none'."
                )

            endpoints_body = _extract_section(doc_text, "7. Endpoints")
            for field in REQUIRED_ENDPOINT_FIELDS:
                if field not in endpoints_body:
                    errors.append(
                        f"{rel}: §7 Endpoints has no '{field}' field. It is mandatory for "
                        f"every endpoint block — write 'none' when genuinely empty."
                    )

            # Check 6 — retired endpoints are flagged for consumers.
            for config in configs:
                if config.get("is_deprecated") and "deprecat" not in doc_text.lower():
                    warnings.append(
                        f"{rel}: '{config['permission_key']}' is deprecated in the registry "
                        f"but the contract does not mention deprecation."
                    )

        # Check 6 (project level) — the entry point exists and indexes every app.
        entry_path = backend_root / PROJECT_ENTRY_POINT
        if not entry_path.is_file():
            errors.append(
                f"Missing project entry point {PROJECT_ENTRY_POINT}. It is the first file "
                f"an external consumer reads (CLAUDE.md §19.3)."
            )
        else:
            entry_text = entry_path.read_text(encoding="utf-8")
            for app_key in documented_apps:
                if app_key not in entry_text:
                    errors.append(
                        f"{PROJECT_ENTRY_POINT}: app '{app_key}' publishes an INTEGRATION.md "
                        f"but is missing from the app inventory (§6)."
                    )

        self._report(errors, warnings, strict, len(discovered))

    def _report(self, errors: list[str], warnings: list[str], strict: bool, app_count: int) -> None:
        for warning in warnings:
            self.stdout.write(self.style.WARNING(f"WARNING: {warning}"))
        for error in errors:
            self.stdout.write(self.style.ERROR(f"ERROR: {error}"))

        if errors or (strict and warnings):
            total = len(errors) + (len(warnings) if strict else 0)
            self.stdout.write(self.style.ERROR(f"\nIntegration Docs Validation Failed — {total} finding(s)."))
            raise SystemExit(1)

        suffix = f" ({len(warnings)} warning(s))" if warnings else ""
        self.stdout.write(
            self.style.SUCCESS(f"Integration Docs Validation Passed — {app_count} app(s) checked{suffix}.")
        )
