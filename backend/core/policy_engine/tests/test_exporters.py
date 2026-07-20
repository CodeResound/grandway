import json
from pathlib import Path

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from core.policy_engine.constants import (
    DependencyDirection,
    DependencyType,
    EnforcementMode,
    OperationType,
    RiskLevel,
)
from core.policy_engine.exporters import (
    _route_to_openapi_path,
    build_openapi_document,
    build_registry_export,
)
from core.policy_engine.validators import _REQUIRED_CONFIG_KEYS

_DOCS_DIR = Path(__file__).resolve().parents[1] / "docs"


class RegistryExportTest(TestCase):
    def setUp(self):
        self.export = build_registry_export()

    def test_endpoints_sorted_by_permission_key(self):
        keys = [e["permission_key"] for e in self.export["endpoints"]]
        self.assertEqual(keys, sorted(keys))

    def test_export_is_deterministic(self):
        self.assertEqual(build_registry_export(), build_registry_export())

    def test_endpoint_count_matches(self):
        self.assertEqual(self.export["endpoint_count"], len(self.export["endpoints"]))

    def test_known_endpoint_present_with_dependency(self):
        by_key = {e["permission_key"]: e for e in self.export["endpoints"]}
        # The policy engine self-registers its own read-only endpoints:
        # policy_engine.application.read requires policy_engine.application.list.
        self.assertIn("policy_engine.application.read", by_key)
        targets = [d["target_permission_key"] for d in by_key["policy_engine.application.read"]["dependencies"]]
        self.assertIn("policy_engine.application.list", targets)

    def test_generated_from_registry(self):
        self.assertEqual(self.export["generated_from"], "registry")


class OpenApiDocumentTest(TestCase):
    def setUp(self):
        self.doc = build_openapi_document()

    def test_top_level_structure(self):
        self.assertEqual(self.doc["openapi"], "3.1.0")
        self.assertIn("paths", self.doc)
        self.assertIn("components", self.doc)
        self.assertIn("SuccessEnvelope", self.doc["components"]["schemas"])
        self.assertIn("ErrorEnvelope", self.doc["components"]["schemas"])

    def test_path_templating_converts_django_params(self):
        self.assertEqual(_route_to_openapi_path("/api/v1/auth/users/<uuid:id>/"), "/api/v1/auth/users/{id}/")
        self.assertEqual(
            _route_to_openapi_path("/api/v1/policy/apps/<str:app_key>/"), "/api/v1/policy/apps/{app_key}/"
        )
        self.assertEqual(_route_to_openapi_path("/api/v1/auth/users/<id>/"), "/api/v1/auth/users/{id}/")

    def test_operations_carry_permission_extension_and_operation_id(self):
        for methods in self.doc["paths"].values():
            for op in methods.values():
                self.assertIn("x-permission-key", op)
                self.assertEqual(op["operationId"], op["x-permission-key"])
                self.assertIn("bearerAuth", op["security"][0])

    def test_no_unconverted_django_params_remain(self):
        for path in self.doc["paths"]:
            self.assertNotIn("<", path)
            self.assertNotIn(">", path)


class RegistrySchemaContractTest(TestCase):
    """The published registry_schema.json must stay in sync with the Python
    validator's required keys and the constant enums — otherwise the machine
    contract silently drifts from what sync_policy_registry actually enforces."""

    def setUp(self):
        self.schema = json.loads((_DOCS_DIR / "registry_schema.json").read_text(encoding="utf-8"))

    def test_required_keys_match_validator(self):
        self.assertEqual(sorted(self.schema["required"]), sorted(_REQUIRED_CONFIG_KEYS))

    def test_enums_match_constants(self):
        props = self.schema["properties"]
        self.assertEqual(sorted(props["operation_type"]["enum"]), sorted(OperationType.values))
        self.assertEqual(sorted(props["risk_level"]["enum"]), sorted(RiskLevel.values))
        dep = self.schema["$defs"]["dependency"]["properties"]
        self.assertEqual(sorted(dep["direction"]["enum"]), sorted(DependencyDirection.values))
        self.assertEqual(sorted(dep["dependency_type"]["enum"]), sorted(DependencyType.values))
        self.assertEqual(sorted(dep["enforcement_mode"]["enum"]), sorted(EnforcementMode.values))


class ExportCommandCheckTest(TestCase):
    def test_check_passes_against_committed_artifacts(self):
        # The committed artifacts must be fresh (CI enforces this too).
        call_command("export_policy_registry", format="registry", check=True)
        call_command("export_policy_registry", format="openapi", check=True)

    def test_check_fails_when_committed_artifact_is_stale(self):
        # Point the command at a temp stale file by monkeypatching the committed map.
        from core.policy_engine.management.commands import export_policy_registry as cmd

        original = cmd._COMMITTED_ARTIFACT["registry"]
        stale = _DOCS_DIR / "_stale_test_artifact.json"
        stale.write_text('{"drift": true}\n', encoding="utf-8")
        cmd._COMMITTED_ARTIFACT["registry"] = stale
        try:
            with self.assertRaises(CommandError):
                call_command("export_policy_registry", format="registry", check=True)
        finally:
            cmd._COMMITTED_ARTIFACT["registry"] = original
            stale.unlink()
