from .base import *  # noqa: F401, F403

DEBUG = False

# Refresh token is an HttpOnly cookie in staging; never the dev "body" mode.
AUTH_COOKIE_STRATEGY = "cookie"

SECURE_SSL_REDIRECT = True
SECURE_HSTS_SECONDS = 3600
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
