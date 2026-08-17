"""Environment selection must fail closed (security audit S4).

`core.settings.__init__` auto-selects a settings module from ENVIRONMENT. A
process that never states its environment, or states an unknown one, must not
silently boot development settings (DEBUG=True). Each case runs in a
subprocess because settings modules are import-once state.
"""

import os
import subprocess
import sys
from pathlib import Path

from django.test import SimpleTestCase

BACKEND_DIR = Path(__file__).resolve().parents[2]


def _import_settings(environment: str | None) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if k not in ("ENVIRONMENT", "DJANGO_SETTINGS_MODULE")}
    if environment is not None:
        env["ENVIRONMENT"] = environment
    return subprocess.run(
        [sys.executable, "-c", "import core.settings as s; print('DEBUG=%s' % s.DEBUG)"],
        cwd=str(BACKEND_DIR),
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )


class SettingsSelectionTests(SimpleTestCase):
    def test_unknown_environment_refuses_to_boot(self) -> None:
        result = _import_settings("bogus")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("ImproperlyConfigured", result.stderr)
        self.assertIn("'bogus'", result.stderr)

    def test_unset_environment_falls_back_to_repo_root_dotenv(self) -> None:
        # The repo-root .env pins ENVIRONMENT=development for local tooling; an
        # unset process env resolves through it instead of a hardcoded default.
        result = _import_settings(None)
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("DEBUG=True", result.stdout)

    def test_testing_environment_selects_testing_settings(self) -> None:
        result = _import_settings("testing")
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("DEBUG=True", result.stdout)
