"""Environment selection must fail closed (security audit S4).

`core.settings.__init__` auto-selects a settings module from ENVIRONMENT. A
process that never states its environment, or states an unknown one, must not
silently boot development settings (DEBUG=True). Each case runs in a
subprocess because settings modules are import-once state.
"""

import os
import shutil
import subprocess
import sys
import tempfile
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


class StrayDotEnvGuardTests(SimpleTestCase):
    """A .env on a production host must not silently downgrade the environment.

    ENVIRONMENT unset with no .env raises — that is fail-closed. ENVIRONMENT
    unset *with* a developer's .env silently selected development: DEBUG=True,
    no HTTPS redirect, no HSTS, stack traces to clients, no error and no
    warning. The presence of .env.production proves the host is meant to serve
    production, so a .env saying otherwise is a misconfiguration.

    Found by the v1.0.0 production smoke boot, 2026-08-19.
    """

    def _run_in(self, root: Path) -> subprocess.CompletedProcess:
        backend = root / "backend"
        env = {k: v for k, v in os.environ.items() if k not in ("ENVIRONMENT", "DJANGO_SETTINGS_MODULE")}
        env.update(
            {
                "SECRET_KEY": "test-only-not-a-real-key",
                "DB_NAME": "x",
                "DB_USER": "x",
                "DB_PASSWORD": "x",
                "ALLOWED_HOSTS": "app.example.com",
                "CORS_ALLOWED_ORIGINS": "https://app.example.com",
                "CSRF_TRUSTED_ORIGINS": "https://app.example.com",
                "CACHE_BACKEND": "django.core.cache.backends.locmem.LocMemCache",
                "THROTTLE_SINGLE_WORKER": "true",
            }
        )
        return subprocess.run(
            [sys.executable, "-c", "import core.settings as s; print('DEBUG=%s' % s.DEBUG)"],
            cwd=str(backend),
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )

    def _fake_repo(self, tmp: str, *, env_contents: str | None, production_marker: bool) -> Path:
        """Mirror the real layout: <root>/backend/core/settings/ plus root env files."""
        root = Path(tmp) / "repo"
        (root / "backend").mkdir(parents=True)
        # Copy rather than symlink: settings resolves its own path to find the
        # repo root, and resolve() follows symlinks straight back to the real
        # tree, which would defeat the whole fixture. ~1 MB.
        shutil.copytree(
            BACKEND_DIR / "core",
            root / "backend" / "core",
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "tests"),
        )
        if env_contents is not None:
            (root / ".env").write_text(env_contents)
        if production_marker:
            (root / ".env.production").write_text("# marker only\n")
        # development.py reads .env.development unconditionally.
        (root / ".env.development").write_text(
            "SECRET_KEY=test-only-not-a-real-key\nDB_NAME=x\nDB_USER=x\nDB_PASSWORD=x\n"
        )
        return root

    def test_stray_dev_dotenv_beside_production_marker_refuses_to_boot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self._fake_repo(tmp, env_contents="ENVIRONMENT=development\n", production_marker=True)
            result = self._run_in(root)
            self.assertNotEqual(result.returncode, 0, msg=result.stdout)
            self.assertIn("ImproperlyConfigured", result.stderr)
            self.assertIn(".env.production", result.stderr)

    def test_dev_dotenv_alone_still_boots(self) -> None:
        # The ordinary developer case must keep working.
        with tempfile.TemporaryDirectory() as tmp:
            root = self._fake_repo(tmp, env_contents="ENVIRONMENT=development\n", production_marker=False)
            result = self._run_in(root)
            self.assertEqual(result.returncode, 0, msg=result.stderr)
            self.assertIn("DEBUG=True", result.stdout)
