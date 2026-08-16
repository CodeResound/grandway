from decouple import Csv, config

from .base import *  # noqa: F401, F403

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
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
CORS_ALLOWED_ORIGINS = config("CORS_ALLOWED_ORIGINS", cast=Csv())
CORS_ALLOW_CREDENTIALS = True
CSRF_TRUSTED_ORIGINS = config("CSRF_TRUSTED_ORIGINS", cast=Csv())

SECURE_SSL_REDIRECT = True
SECURE_HSTS_SECONDS = 3600
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
