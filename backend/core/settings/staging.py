from pathlib import Path

import decouple
from decouple import Csv

# Same env-file rule as production.py, pointed at .env.staging: read the file
# when present, otherwise OS environment only — never decouple's default
# search, which could consume a stray dev-valued `.env`.
_env_file = Path(__file__).resolve().parents[3] / ".env.staging"
if _env_file.exists():
    decouple.config = decouple.Config(decouple.RepositoryEnv(str(_env_file)))
else:
    decouple.config = decouple.Config(decouple.RepositoryEmpty())
config = decouple.config

from .base import *  # noqa: E402, F401, F403

DEBUG = False

# Refresh token is an HttpOnly cookie in staging; never the dev "body" mode.
#
# This line previously read `AUTH_COOKIE_STRATEGY = "cookie"`, which no code has
# ever read — authenticate/views.py branches on AUTH_REFRESH_COOKIE_ENABLED, and
# base.py leaves that False. So staging asserted the cookie transport in a
# comment while actually returning the refresh token in the JSON response body,
# where any script on the page can read it. Staging holds real enough data to
# make that matter, and it is the environment where the cookie path gets
# exercised before production depends on it.
AUTH_REFRESH_COOKIE_ENABLED = True

# See production.py for why each of these is required rather than defaulted:
# without SECURE_PROXY_SSL_HEADER, SECURE_SSL_REDIRECT below is a redirect loop
# behind a TLS-terminating proxy; without the origin lists the browser cannot
# call the API or send the refresh cookie at all.
# ---------------------------------------------------------------------------
# Parity with production (see production.py for the full reasoning on each).
#
# Staging exists to exercise production's posture before production depends on
# it. Every rule production enforces, staging enforces too — a staging that is
# materially laxer cannot validate anything. Only *values* may be softer, and
# exactly one is: HSTS runs at an hour instead of a year, with no preload, so a
# staging hostname is never burned into browser preload lists.
# ---------------------------------------------------------------------------
ALLOWED_HOSTS = config("ALLOWED_HOSTS", cast=Csv())  # required, no default

CACHES["default"]["BACKEND"] = config("CACHE_BACKEND")  # noqa: F405 — required, no default
if "locmem" in CACHES["default"]["BACKEND"] and not config(  # noqa: F405
    "THROTTLE_SINGLE_WORKER", default=False, cast=bool
):
    from django.core.exceptions import ImproperlyConfigured

    raise ImproperlyConfigured(
        "CACHE_BACKEND is LocMemCache: rate limits are per-process and reset on "
        "restart. Set a shared cache backend, or set THROTTLE_SINGLE_WORKER=true "
        "to acknowledge a single-worker deployment."
    )

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
CORS_ALLOWED_ORIGINS = config("CORS_ALLOWED_ORIGINS", cast=Csv())
CORS_ALLOW_CREDENTIALS = True
CSRF_TRUSTED_ORIGINS = config("CSRF_TRUSTED_ORIGINS", cast=Csv())

SECURE_SSL_REDIRECT = True

# ---------------------------------------------------------------------------
# Health-probe exemption.
#
# SECURE_SSL_REDIRECT above 301s every request Django considers insecure. A
# load balancer or process supervisor probes /health/ and /ready/ over plain
# HTTP on the loopback, without the X-Forwarded-Proto the proxy adds to real
# traffic — so every probe would get a 301, the balancer would read that as
# "not 200, not healthy", and it would never route traffic to a box that is
# in fact serving fine. That is a first-deploy outage caused entirely by a
# security setting working as designed.
#
# Patterns are matched by SecurityMiddleware against path.lstrip("/"), so
# they carry no leading slash. Exempting these two costs nothing: both are
# public and unauthenticated by design (§23), and neither returns data worth
# protecting in transit.
# ---------------------------------------------------------------------------
SECURE_REDIRECT_EXEMPT = [r"^health/$", r"^ready/$"]
SECURE_HSTS_SECONDS = 3600
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"
