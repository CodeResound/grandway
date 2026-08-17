from pathlib import Path

import decouple
from decouple import Csv

# §10: production reads .env.production when the file exists. When it does not,
# fall back to the OS environment ONLY (RepositoryEmpty) — never decouple's
# default search path, which would silently consume a stray dev-valued `.env`
# sitting in the working directory. Must run before `from .base import *` so
# base.py's config() reads the right source.
_env_file = Path(__file__).resolve().parents[3] / ".env.production"
if _env_file.exists():
    decouple.config = decouple.Config(decouple.RepositoryEnv(str(_env_file)))
else:
    decouple.config = decouple.Config(decouple.RepositoryEmpty())
config = decouple.config

from .base import *  # noqa: E402, F401, F403

DEBUG = False

# Refresh token is a Secure HttpOnly cookie in production; never the dev "body" mode.
# AUTH_REFRESH_COOKIE_ENABLED is the setting authenticate/views.py actually reads;
# the *_SECURE/HTTPONLY/SAMESITE flags are inherited from base.py (Secure +
# HttpOnly + Lax).
AUTH_REFRESH_COOKIE_ENABLED = True

# ---------------------------------------------------------------------------
# TLS termination.
#
# SECURE_SSL_REDIRECT below sends any request Django considers insecure to https.
# Behind a TLS-terminating proxy every proxied request arrives over plain HTTP on
# the loopback, so without this header Django judges all of them insecure and
# redirects them — to a URL that terminates at the same proxy and arrives over
# HTTP again. That is an unconditional redirect loop: the whole site, down, on
# the first request after deploy.
#
# The proxy MUST strip any client-supplied X-Forwarded-Proto and set it itself.
# If it forwards the client's value, this becomes a way to tell Django a plain
# HTTP request was secure, and the secure-cookie flags stop meaning anything.
# ---------------------------------------------------------------------------
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# ---------------------------------------------------------------------------
# Browser origins.
#
# django-cors-headers denies every cross-origin request when CORS_ALLOWED_ORIGINS
# is unset, and CORS_ALLOW_CREDENTIALS defaults to False — so a frontend served
# from its own domain could neither call the API nor send the refresh cookie.
# There is no safe default to guess here, so these are required environment
# values: a deployment that forgets them fails visibly in the browser rather than
# quietly widening access.
#
# ALLOW_ALL_ORIGINS is never set in this file. With CORS_ALLOW_CREDENTIALS on it
# would let any site on the internet make authenticated calls with the user's
# refresh cookie attached.
# ---------------------------------------------------------------------------
CORS_ALLOWED_ORIGINS = config("CORS_ALLOWED_ORIGINS", cast=Csv())
CORS_ALLOW_CREDENTIALS = True
CSRF_TRUSTED_ORIGINS = config("CSRF_TRUSTED_ORIGINS", cast=Csv())

SECURE_SSL_REDIRECT = True
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"
