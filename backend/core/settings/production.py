from .base import *  # noqa: F401, F403

DEBUG = False

# Refresh token is a Secure HttpOnly cookie in production; never the dev "body" mode.
# AUTH_REFRESH_COOKIE_ENABLED drives authenticate.views; the *_SECURE/HTTPONLY/SAMESITE
# flags are inherited from base.py (Secure + HttpOnly + Lax).
AUTH_COOKIE_STRATEGY = "cookie"
AUTH_REFRESH_COOKIE_ENABLED = True

SECURE_SSL_REDIRECT = True
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"
