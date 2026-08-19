"""Health probes must survive SECURE_SSL_REDIRECT in production and staging.

A load balancer probes /health/ and /ready/ over plain HTTP, without the
X-Forwarded-Proto a proxy adds to real traffic. Without SECURE_REDIRECT_EXEMPT
every probe gets a 301, the balancer reads "not healthy", and it never routes
to a box that is serving fine — a first-deploy outage produced by a security
setting working exactly as designed.

Subprocess-based for the same reason as test_settings_selection: settings
modules are import-once state, so a different one cannot be exercised in
process.
"""

import os
import subprocess
import sys
from pathlib import Path

from django.test import SimpleTestCase

BACKEND_DIR = Path(__file__).resolve().parents[2]

_BASE_ENV = {
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


def _boot(environment: str) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if k not in ("ENVIRONMENT", "DJANGO_SETTINGS_MODULE")}
    env.update(_BASE_ENV)
    env["ENVIRONMENT"] = environment
    return subprocess.run(
        [
            sys.executable,
            "-c",
            "import core.settings as s; print('EXEMPT=%s' % s.SECURE_REDIRECT_EXEMPT); "
            "print('REDIRECT=%s' % s.SECURE_SSL_REDIRECT)",
        ],
        cwd=str(BACKEND_DIR),
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )


class HealthProbeExemptionTests(SimpleTestCase):
    def test_production_exempts_both_probes(self) -> None:
        result = _boot("production")
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("REDIRECT=True", result.stdout)
        self.assertIn("^health/$", result.stdout)
        self.assertIn("^ready/$", result.stdout)

    def test_staging_exempts_both_probes(self) -> None:
        result = _boot("staging")
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("REDIRECT=True", result.stdout)
        self.assertIn("^health/$", result.stdout)
        self.assertIn("^ready/$", result.stdout)

    def test_patterns_have_no_leading_slash(self) -> None:
        # SecurityMiddleware matches against path.lstrip("/"); a leading slash
        # would silently never match and the exemption would be inert.
        result = _boot("production")
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertNotIn("^/health/", result.stdout)
        self.assertNotIn("^/ready/", result.stdout)
