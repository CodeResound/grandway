"""The three writable deployment paths must be relocatable and fail loudly.

A VPS puts static under the web root it serves, media deliberately outside any
web root, and logs under /var/log — none of them inside the git checkout. All
three were previously either hardcoded (LOG_DIR, STATIC_ROOT) or, in LOG_DIR's
case, created by an unguarded mkdir at settings-import time that took the whole
process down with a bare OSError naming no setting.

Subprocess-based: settings modules are import-once state.
"""

import os
import subprocess
import sys
import tempfile
from pathlib import Path

from django.test import SimpleTestCase

BACKEND_DIR = Path(__file__).resolve().parents[2]

_BASE_ENV = {
    "ENVIRONMENT": "production",
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

_PROBE = (
    "import core.settings as s; "
    "print('LOG=%s' % s.LOG_DIR); print('STATIC=%s' % s.STATIC_ROOT); print('MEDIA=%s' % s.MEDIA_ROOT)"
)


def _boot(**extra_env: str) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if k not in ("ENVIRONMENT", "DJANGO_SETTINGS_MODULE")}
    env.update(_BASE_ENV)
    env.update(extra_env)
    return subprocess.run(
        [sys.executable, "-c", _PROBE],
        cwd=str(BACKEND_DIR),
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )


class DeploymentPathTests(SimpleTestCase):
    def test_all_three_paths_are_relocatable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = _boot(
                LOG_DIR=f"{tmp}/log",
                STATIC_ROOT=f"{tmp}/www/static",
                MEDIA_ROOT=f"{tmp}/lib/media",
            )
            self.assertEqual(result.returncode, 0, msg=result.stderr)
            self.assertIn(f"LOG={tmp}/log", result.stdout)
            self.assertIn(f"STATIC={tmp}/www/static", result.stdout)
            self.assertIn(f"MEDIA={tmp}/lib/media", result.stdout)

    def test_log_dir_is_created_with_missing_parents(self) -> None:
        # The old mkdir lacked parents=True, so a nested target raised
        # FileNotFoundError at import even when the location was writable.
        with tempfile.TemporaryDirectory() as tmp:
            nested = f"{tmp}/a/b/c"
            result = _boot(LOG_DIR=nested)
            self.assertEqual(result.returncode, 0, msg=result.stderr)
            self.assertTrue(Path(nested).is_dir())

    def test_unwritable_log_dir_refuses_to_boot_with_a_named_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            blocked = Path(tmp) / "ro"
            blocked.mkdir()
            blocked.chmod(0o500)  # r-x: cannot create children
            try:
                result = _boot(LOG_DIR=str(blocked / "logs"))
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("ImproperlyConfigured", result.stderr)
                self.assertIn("LOG_DIR", result.stderr)
            finally:
                blocked.chmod(0o700)

    def test_defaults_remain_repo_relative(self) -> None:
        result = _boot()
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("logs", result.stdout)
        self.assertIn("staticfiles", result.stdout)
        self.assertIn("mediafiles", result.stdout)
