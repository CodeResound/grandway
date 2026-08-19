"""Production must state ALLOWED_HOSTS rather than inherit base's localhost default.

base.py defaults to localhost,127.0.0.1 so `runserver` needs no ceremony.
Inheriting that in production rejects every request on the real hostname with
a 400: the app is up, the proxy is fine, and nothing works. It fails closed,
but at request time rather than boot time — so the first signal is an outage
instead of a refused deploy.

Subprocess-based: settings modules are import-once state.
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
    "CORS_ALLOWED_ORIGINS": "https://app.example.com",
    "CSRF_TRUSTED_ORIGINS": "https://app.example.com",
    "CACHE_BACKEND": "django.core.cache.backends.locmem.LocMemCache",
    "THROTTLE_SINGLE_WORKER": "true",
}


def _boot_production(**extra_env: str) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if k not in ("ENVIRONMENT", "DJANGO_SETTINGS_MODULE")}
    env.update(_BASE_ENV)
    env.update(extra_env)
    return subprocess.run(
        [sys.executable, "-c", "import core.settings as s; print('HOSTS=%s' % s.ALLOWED_HOSTS)"],
        cwd=str(BACKEND_DIR),
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )


class ProductionAllowedHostsTests(SimpleTestCase):
    def test_missing_allowed_hosts_refuses_to_boot(self) -> None:
        result = _boot_production()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("ALLOWED_HOSTS", result.stderr)

    def test_supplied_allowed_hosts_is_honoured(self) -> None:
        result = _boot_production(ALLOWED_HOSTS="admin.example.com,api.example.com")
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("admin.example.com", result.stdout)
        self.assertIn("api.example.com", result.stdout)

    def test_does_not_fall_back_to_localhost(self) -> None:
        result = _boot_production(ALLOWED_HOSTS="admin.example.com")
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertNotIn("127.0.0.1", result.stdout)
