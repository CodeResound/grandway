"""Staging must enforce every rule production enforces.

Staging exists to exercise production's posture before production depends on
it. A staging that is materially laxer than production cannot validate
anything — the first environment where a header or a mandatory setting is
exercised would be production itself.

Only *values* may be softer, and exactly one is: HSTS runs at an hour instead
of a year with no preload, so a staging hostname is never burned into browser
preload lists. That exception is asserted explicitly below so it stays
deliberate rather than becoming cover for future drift.

Subprocess-based: settings modules are import-once state.
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

# Settings whose value must be identical in staging and production.
_MUST_MATCH = (
    "DEBUG",
    "SECURE_SSL_REDIRECT",
    "SECURE_REDIRECT_EXEMPT",
    "SECURE_HSTS_INCLUDE_SUBDOMAINS",
    "SECURE_BROWSER_XSS_FILTER",
    "SECURE_CONTENT_TYPE_NOSNIFF",
    "X_FRAME_OPTIONS",
    "SESSION_COOKIE_SECURE",
    "CSRF_COOKIE_SECURE",
    "SECURE_PROXY_SSL_HEADER",
    "AUTH_REFRESH_COOKIE_ENABLED",
)

_PROBE = "import core.settings as s; print(repr({{{}}}))".format(", ".join(f"{k!r}: s.{k}" for k in _MUST_MATCH))


def _dump(environment: str, **extra_env: str) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if k not in ("ENVIRONMENT", "DJANGO_SETTINGS_MODULE")}
    env.update(_BASE_ENV)
    env.update(extra_env)
    env["ENVIRONMENT"] = environment
    return subprocess.run(
        [sys.executable, "-c", _PROBE],
        cwd=str(BACKEND_DIR),
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )


class StagingParityTests(SimpleTestCase):
    def test_security_settings_match_production(self) -> None:
        prod = _dump("production")
        stag = _dump("staging")
        self.assertEqual(prod.returncode, 0, msg=prod.stderr)
        self.assertEqual(stag.returncode, 0, msg=stag.stderr)
        self.assertEqual(
            eval(stag.stdout.strip()),  # noqa: S307 — our own repr, from our own subprocess
            eval(prod.stdout.strip()),  # noqa: S307
            msg="staging drifted from production; soften values, never drop rules",
        )

    def test_staging_requires_cache_backend(self) -> None:
        env = {k: v for k, v in _BASE_ENV.items() if k != "CACHE_BACKEND"}
        result = subprocess.run(
            [sys.executable, "-c", "import core.settings as s"],
            cwd=str(BACKEND_DIR),
            env={
                **{k: v for k, v in os.environ.items() if k not in ("ENVIRONMENT", "DJANGO_SETTINGS_MODULE")},
                **env,
                "ENVIRONMENT": "staging",
            },
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("CACHE_BACKEND", result.stderr)

    def test_staging_requires_allowed_hosts(self) -> None:
        env = {k: v for k, v in _BASE_ENV.items() if k != "ALLOWED_HOSTS"}
        result = subprocess.run(
            [sys.executable, "-c", "import core.settings as s"],
            cwd=str(BACKEND_DIR),
            env={
                **{k: v for k, v in os.environ.items() if k not in ("ENVIRONMENT", "DJANGO_SETTINGS_MODULE")},
                **env,
                "ENVIRONMENT": "staging",
            },
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("ALLOWED_HOSTS", result.stderr)

    def test_hsts_is_deliberately_weaker_in_staging(self) -> None:
        # The one permitted divergence. If this test fails because staging was
        # raised to production's values, delete the test — do not weaken it.
        probe = "import core.settings as s; print('%s|%s' % (s.SECURE_HSTS_SECONDS, getattr(s, 'SECURE_HSTS_PRELOAD', False)))"
        env = {k: v for k, v in os.environ.items() if k not in ("ENVIRONMENT", "DJANGO_SETTINGS_MODULE")}
        env.update(_BASE_ENV)
        env["ENVIRONMENT"] = "staging"
        result = subprocess.run(
            [sys.executable, "-c", probe], cwd=str(BACKEND_DIR), env=env, capture_output=True, text=True, timeout=60
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        seconds, preload = result.stdout.strip().split("|")
        self.assertEqual(seconds, "3600")
        self.assertEqual(preload, "False")
