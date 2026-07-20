"""Tests for the `validate_integration_docs` management command.

The command is the gate that keeps each app's consumer-facing `INTEGRATION.md`
in step with the endpoint registry (CLAUDE.md §19.1/§19.3). These tests pin each
failure mode so the gate cannot silently stop binding — a gate that passes
unconditionally is worse than no gate, because it reads as proof.

Docs are written to a tmp dir and the app-discovery function is patched, so the
tests never depend on the repo's real INTEGRATION.md content (which would make
them fail for unrelated documentation edits).
"""

import tempfile
from pathlib import Path
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase

_DISCOVER = "core.management.commands.validate_integration_docs._discover_app_endpoints"

SECTIONS = [
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


class _FakeAppConfig:
    """Stands in for a Django AppConfig — only `.path` is read by the command."""

    def __init__(self, path: str) -> None:
        self.path = path


def _build_doc(
    permission_keys: list[str],
    *,
    sections: list[str] | None = None,
    requires_body: str = "| `core` | framework | Envelope | Raw errors |",
    include_requires_state: bool = True,
    include_side_effects: bool = True,
) -> str:
    """Render a minimal but valid INTEGRATION.md, with knobs for each failure mode."""
    parts: list[str] = ["# Integration — Test App\n"]
    for section in sections if sections is not None else SECTIONS:
        parts.append(f"\n## {section}\n")
        if section == "2. Requires":
            parts.append(f"\n{requires_body}\n")
        elif section == "7. Endpoints":
            parts.append("\n### Resource — `/api/v1/test/`\n")
            parts.append("\n**Use it when:** testing.\n")
            for key in permission_keys:
                parts.append(f"\n- `GET /api/v1/test/` (permission: `{key}`)\n")
            if include_requires_state:
                parts.append("\n**Requires state:** none\n")
            if include_side_effects:
                parts.append("\n**Side effects:** none\n")
        else:
            parts.append("\nplaceholder\n")
    return "".join(parts)


class ValidateIntegrationDocsTest(TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.app_dir = Path(self._tmp.name) / "testapp"
        (self.app_dir / "docs").mkdir(parents=True)

        # The command also checks the project entry point relative to the
        # backend root; point it at a stub that indexes our fake app.
        self.core_docs = Path(self._tmp.name) / "core" / "docs"
        self.core_docs.mkdir(parents=True)
        (self.core_docs / "INTEGRATION.md").write_text(
            "# Integration — Test\n\n## 6. App inventory\n\n| testapp | ... |\n",
            encoding="utf-8",
        )

    def _write_doc(self, content: str) -> None:
        (self.app_dir / "docs" / "INTEGRATION.md").write_text(content, encoding="utf-8")

    def _discovered(self, keys: list[str]) -> dict:
        return {
            "testapp": (
                _FakeAppConfig(str(self.app_dir)),
                [{"permission_key": k, "app_key": "testapp"} for k in keys],
            )
        }

    def _run(self, keys: list[str], *, strict: bool = False) -> None:
        """Run the command with app discovery and the backend root both pinned."""
        with (
            patch(_DISCOVER, return_value=self._discovered(keys)),
            patch("core.management.commands.validate_integration_docs.apps.get_app_config") as get_cfg,
        ):
            get_cfg.return_value = _FakeAppConfig(str(Path(self._tmp.name) / "core"))
            call_command("validate_integration_docs", *(["--strict"] if strict else []))

    def test_passes_when_contract_is_complete(self) -> None:
        self._write_doc(_build_doc(["testapp.resource.list"]))
        self._run(["testapp.resource.list"])  # must not raise

    def test_fails_when_integration_doc_is_missing(self) -> None:
        # No file written at all.
        with self.assertRaises(SystemExit):
            self._run(["testapp.resource.list"])

    def test_fails_when_registered_endpoint_is_undocumented(self) -> None:
        self._write_doc(_build_doc(["testapp.resource.list"]))
        with self.assertRaises(SystemExit):
            self._run(["testapp.resource.list", "testapp.resource.create"])

    def test_fails_on_stale_key_not_in_registry(self) -> None:
        self._write_doc(_build_doc(["testapp.resource.list", "testapp.resource.ghost"]))
        with self.assertRaises(SystemExit):
            self._run(["testapp.resource.list"])

    def test_fails_when_required_section_missing(self) -> None:
        self._write_doc(_build_doc(["testapp.resource.list"], sections=[s for s in SECTIONS if s != "5. Enums"]))
        with self.assertRaises(SystemExit):
            self._run(["testapp.resource.list"])

    def test_fails_when_sections_out_of_order(self) -> None:
        reordered = SECTIONS.copy()
        reordered[3], reordered[4] = reordered[4], reordered[3]
        self._write_doc(_build_doc(["testapp.resource.list"], sections=reordered))
        with self.assertRaises(SystemExit):
            self._run(["testapp.resource.list"])

    def test_fails_when_requires_section_is_empty(self) -> None:
        self._write_doc(_build_doc(["testapp.resource.list"], requires_body=""))
        with self.assertRaises(SystemExit):
            self._run(["testapp.resource.list"])

    def test_fails_when_requires_state_field_missing(self) -> None:
        self._write_doc(_build_doc(["testapp.resource.list"], include_requires_state=False))
        with self.assertRaises(SystemExit):
            self._run(["testapp.resource.list"])

    def test_fails_when_side_effects_field_missing(self) -> None:
        self._write_doc(_build_doc(["testapp.resource.list"], include_side_effects=False))
        with self.assertRaises(SystemExit):
            self._run(["testapp.resource.list"])

    def test_fails_when_app_missing_from_project_entry_point(self) -> None:
        (self.core_docs / "INTEGRATION.md").write_text(
            "# Integration — Test\n\n## 6. App inventory\n\nno apps listed\n", encoding="utf-8"
        )
        self._write_doc(_build_doc(["testapp.resource.list"]))
        with self.assertRaises(SystemExit):
            self._run(["testapp.resource.list"])

    def test_literal_none_satisfies_mandatory_depth_fields(self) -> None:
        """'none' is an answer; silence is not. This is the load-bearing convention."""
        doc = _build_doc(["testapp.resource.list"])
        self.assertIn("**Requires state:** none", doc)
        self.assertIn("**Side effects:** none", doc)
        self._write_doc(doc)
        self._run(["testapp.resource.list"], strict=True)  # must not raise
