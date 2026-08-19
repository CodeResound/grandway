"""Production must not inherit the per-process throttle cache silently (S5).

DRF throttle counters in LocMemCache multiply every limit by the gunicorn
worker count and reset on restart. `core.settings.production` requires
CACHE_BACKEND explicitly and refuses LocMemCache unless the operator
acknowledges a single-worker deployment. Subprocess-based for the same reason
as test_settings_selection: settings modules are import-once state.
"""

import os
import subprocess
import sys
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
}


def _boot_production(**extra_env: str) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if k not in ("ENVIRONMENT", "DJANGO_SETTINGS_MODULE")}
    env.update(_BASE_ENV)
    env.update(extra_env)
    return subprocess.run(
        [sys.executable, "-c", "import core.settings as s; print('BACKEND=%s' % s.CACHES['default']['BACKEND'])"],
        cwd=str(BACKEND_DIR),
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )


class ProductionThrottleCacheTests(SimpleTestCase):
    def test_missing_cache_backend_refuses_to_boot(self) -> None:
        result = _boot_production()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("CACHE_BACKEND", result.stderr)

    def test_locmem_without_acknowledgment_refuses_to_boot(self) -> None:
        result = _boot_production(CACHE_BACKEND="django.core.cache.backends.locmem.LocMemCache")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("ImproperlyConfigured", result.stderr)
        self.assertIn("THROTTLE_SINGLE_WORKER", result.stderr)

    def test_locmem_with_single_worker_acknowledgment_boots(self) -> None:
        result = _boot_production(
            CACHE_BACKEND="django.core.cache.backends.locmem.LocMemCache",
            THROTTLE_SINGLE_WORKER="true",
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("locmem.LocMemCache", result.stdout)

    def test_shared_backend_boots(self) -> None:
        result = _boot_production(CACHE_BACKEND="django.core.cache.backends.db.DatabaseCache")
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("DatabaseCache", result.stdout)
