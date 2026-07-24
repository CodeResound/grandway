import os
import tempfile

# Provide required env defaults so base settings can import without a running DB or .env file
os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production")
os.environ.setdefault("DB_NAME", "test")
os.environ.setdefault("DB_USER", "test")
os.environ.setdefault("DB_PASSWORD", "test")

from .base import *  # noqa: F401, F403, E402

DEBUG = True

# Uploaded files never touch the repository working tree during a test run.
# Individual upload tests still wrap themselves in override_settings with their
# own temp directory so they can clean up; this is the backstop that keeps a
# test which forgets to do so from writing into backend/mediafiles/.
MEDIA_ROOT = tempfile.mkdtemp(prefix="grandway-test-media-")

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}

# DRF throttle state lives in the process cache and is not rolled back between
# tests; disable the scoped auth rates so unrelated tests don't trip them.
# django-axes lockout (DB-backed, rolled back per test) stays enabled so the
# lockout behaviour can be tested directly.
REST_FRAMEWORK = {
    **REST_FRAMEWORK,  # noqa: F405
    "DEFAULT_THROTTLE_RATES": {
        **REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"],  # noqa: F405
        "anon": None,
        "user": None,
        "auth_login_ip": None,
        "auth_login_user": None,
        "auth_refresh": None,
    },
}
