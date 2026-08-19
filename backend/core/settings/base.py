from datetime import timedelta
from pathlib import Path

from decouple import Csv, config

BASE_DIR = Path(__file__).resolve().parent.parent.parent

# ---------------------------------------------------------------------------
# Log directory.
#
# Configurable because the repo-relative default only makes sense for a
# checkout: a deployment that runs from /opt or a container image would
# otherwise write logs back into its own source tree, or fail outright if that
# tree is read-only.
#
# The mkdir is guarded for the same reason. It runs at settings import — before
# SECRET_KEY is even read — so an unwritable path takes down every worker,
# every migrate, every collectstatic and the nightly cron, and it did so with a
# bare OSError traceback that named no setting. A read-only root filesystem or
# a non-root container user is the ordinary way to hit this. Fail with a
# message that says which variable to change.
# ---------------------------------------------------------------------------
LOG_DIR = Path(config("LOG_DIR", default=str(BASE_DIR.parent / "logs")))
try:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
except OSError as exc:
    from django.core.exceptions import ImproperlyConfigured

    raise ImproperlyConfigured(
        f"LOG_DIR ({LOG_DIR}) could not be created: {exc}. Point LOG_DIR at a "
        "writable directory, or pre-create it with write permission for the "
        "user this process runs as."
    ) from exc

SECRET_KEY = config("SECRET_KEY")
ALLOWED_HOSTS = config("ALLOWED_HOSTS", default="localhost,127.0.0.1", cast=Csv())

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Enables the pg_trgm-backed GIN indexes used for Devanagari/romanized
    # name search (§39.6). Ships with Django; not a third-party dependency.
    "django.contrib.postgres",
    # Third-party
    "rest_framework",
    "rest_framework_simplejwt",
    "corsheaders",
    "axes",
    "django_otp",
    "django_otp.plugins.otp_totp",
    # Internal
    "core",
    "core.policy_engine",
    "authenticate",
    "audit",
    "leads",
    "applicants",
    "applicant_journeys",
    "institutions",
    "offers",
    "clients",
    "documents",
    "document_history",
    "document_templates",
    "uploaded_files",
    "checklists",
    "dashboards",
    "notifications",
    "reminders",
    "search",
]

# Switch off every app's signal side effects for this process (§11). Set it for
# bulk imports that would otherwise fire one handler per imported row inside the
# import's own transaction; rebuild afterwards with the owning app's command
# (today: `python manage.py apply_country_checklists`).
DISABLE_SIGNALS = False

# The authenticate app owns the platform's identity layer with a custom user model.
AUTH_USER_MODEL = "authenticate.User"

# How many reverse proxies sit in front of the application, and therefore how far
# from the right of X-Forwarded-For the real client address is. Read once here
# because two separate subsystems need the same answer — DRF's throttles and
# django-axes' lockout — and a deployment where they disagreed would rate-limit
# one identity while locking out another. See REST_FRAMEWORK["NUM_PROXIES"] and
# the AXES_IPWARE_* block for what each does with it.
#
# 0 (the default) means nothing proxies the app: X-Forwarded-For is ignored
# entirely in favour of REMOTE_ADDR. Set it to the real number of hops at deploy
# time — one for a single nginx, two behind nginx + a load balancer. Too low is
# safe (it reads a trusted hop); too high trusts a header the client controls.
_NUM_PROXIES = config("NUM_PROXIES", default=0, cast=int)

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    # Must be early — before CommonMiddleware — so CORS headers reach every response.
    "corsheaders.middleware.CorsMiddleware",
    "core.middleware.RequestIDMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    # django-otp: must sit directly after AuthenticationMiddleware. Provides
    # request.user.is_verified(), which the OTP-gated admin (core.apps) relies
    # on; JWT API requests never carry a session and are unaffected.
    "django_otp.middleware.OTPMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    # django-axes: must be the LAST middleware so it observes the final auth outcome.
    "axes.middleware.AxesMiddleware",
]

ROOT_URLCONF = "core.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "core.wsgi.application"
ASGI_APPLICATION = "core.asgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": config("DB_NAME"),
        "USER": config("DB_USER"),
        "PASSWORD": config("DB_PASSWORD"),
        "HOST": config("DB_HOST", default="localhost"),
        "PORT": config("DB_PORT", default="5432"),
        "CONN_MAX_AGE": config("DB_CONN_MAX_AGE", default=60, cast=int),
    }
}

# ---------------------------------------------------------------------------
# Cache — the store behind DRF's rate limiting.
#
# This is not a performance cache; nothing in this project caches for speed. It
# exists because DRF's throttle classes keep their counters in it, so whatever
# backend is configured here *is* the rate limiter's memory.
#
# Django's implicit default is LocMemCache, which is per-process. Under any real
# deployment (gunicorn with N workers) that silently multiplies every configured
# limit by N and resets all counters on each restart — so `auth_login_ip:
# 20/minute` is really 20 per minute per worker. Naming the backend here makes
# that visible and overridable rather than inherited by accident.
#
# The default stays local: §37 makes local-first the posture, and a single-process
# deployment is correct for it. A multi-worker deployment must point CACHE_URL at
# a shared backend (Redis/Valkey — a derived, rebuildable store per §37) or its
# rate limits are decorative. Guarded by core/tests/test_throttle_backend.py.
# ---------------------------------------------------------------------------
CACHES = {
    "default": {
        "BACKEND": config(
            "CACHE_BACKEND",
            default="django.core.cache.backends.locmem.LocMemCache",
        ),
        "LOCATION": config("CACHE_LOCATION", default="grandway-default"),
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 12},
    },
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# Argon2id is the primary password hasher (argon2-cffi backend, ID variant), per the
# authenticate app's security target. PBKDF2 variants remain as fallback verifiers so
# any pre-existing PBKDF2 hashes still validate and are upgraded on next login.
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2SHA1PasswordHasher",
]

# AxesStandaloneBackend must precede ModelBackend so a locked (username, ip) pair is
# denied before credential verification. ModelBackend does the actual auth.
AUTHENTICATION_BACKENDS = [
    "axes.backends.AxesStandaloneBackend",
    "django.contrib.auth.backends.ModelBackend",
]

# django-axes: brute-force lockout. Sole failed-attempt counter in the system
# (covers /admin/login/ too). Locks independently on username OR ip_address.
AXES_FAILURE_LIMIT = config("AXES_FAILURE_LIMIT", default=5, cast=int)
AXES_COOLOFF_TIME = timedelta(minutes=config("AXES_COOLOFF_MINUTES", default=15, cast=int))
AXES_LOCKOUT_PARAMETERS = ["username", "ip_address"]
AXES_RESET_ON_SUCCESS = True
AXES_ENABLE_ACCESS_FAILURE_LOG = True

# How axes resolves "the client's IP", kept in step with DRF's NUM_PROXIES above
# so the lockout and the throttle can never disagree about who they are counting.
#
# axes defaults to REMOTE_ADDR alone, which is the safe default but the wrong
# answer behind a proxy: REMOTE_ADDR is then the proxy for *every* request, so
# all users share one ip_address bucket. Because AXES_LOCKOUT_PARAMETERS locks on
# ip_address as well as username, one attacker's failures would lock out every
# legitimate user arriving through the same proxy — a self-inflicted outage.
#
# With proxies declared, axes counts in from the right of X-Forwarded-For exactly
# as DRF does. With none (the default 0), REMOTE_ADDR stays authoritative and the
# client-supplied header is ignored.
if _NUM_PROXIES:
    AXES_IPWARE_PROXY_COUNT = _NUM_PROXIES
    AXES_IPWARE_META_PRECEDENCE_ORDER = ("HTTP_X_FORWARDED_FOR", "REMOTE_ADDR")

# django-otp: TOTP MFA. The issuer label shown in authenticator apps. No
# OTPMiddleware is installed — the authenticate login service verifies TOTP codes
# directly and binds MFA state to the session it issues.
OTP_TOTP_ISSUER = config("OTP_TOTP_ISSUER", default="Grandway")

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
# Configurable so a deployment can collect into the path its web server
# actually serves (e.g. /var/www/<project>/static) rather than a directory
# inside the checkout. Unlike MEDIA_ROOT below, this content is public by
# design — it is exactly what the reverse proxy should serve.
STATIC_ROOT = Path(config("STATIC_ROOT", default=str(BASE_DIR / "staticfiles")))

# ---------------------------------------------------------------------------
# Uploaded file storage — the uploaded_files app (CLAUDE.md §14, §37).
#
# MEDIA_ROOT is the project's only byte store and is deliberately LOCAL: §37
# makes local-first the default posture, and applicant passports, transcripts,
# and bank statements are precisely the data that should not leave the machine
# by default.
#
# **Nothing serves MEDIA_ROOT.** core/urls.py routes exactly four prefixes —
# admin/, health/, ready/, and api/v1/ — and none of them is a static file
# handler, so no URL maps to the storage volume in any environment. The only
# path from the disk to a client is the authenticated download endpoint
# GET /api/v1/files/<id>/download/, which applies the same authority check as
# every other route. A guessable media URL would defeat "privacy by default"
# (concepts/project_overview.txt) for the most sensitive data in the system.
#
# MEDIA_URL is left at Django's default (which normalizes to "/") rather than
# being set to anything: it is the prefix FileField.url would build, and since
# nothing in this project ever calls .url or serves the volume, its value is
# inert. Do NOT add django.conf.urls.static.static(MEDIA_URL, ...) to
# core/urls.py for local convenience — that single line would publish every
# applicant passport at a guessable path. Guarded by
# core/tests/test_media_is_not_served.py.
#
# The default lands inside backend/mediafiles/, which .gitignore already covers,
# so development uploads can never be committed. Deployments override it with a
# path on a real volume.
# ---------------------------------------------------------------------------
MEDIA_ROOT = Path(config("MEDIA_ROOT", default=str(BASE_DIR / "mediafiles")))

# Files land on disk readable by the owner and the group only. Django's default
# (0o644) would make every applicant document world-readable to any account on
# the host.
FILE_UPLOAD_PERMISSIONS = 0o640
FILE_UPLOAD_DIRECTORY_PERMISSIONS = 0o750

# One file per request — every upload endpoint in this project accepts exactly
# one. A request carrying more is rejected by Django before any view runs.
DATA_UPLOAD_MAX_NUMBER_FILES = 1

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "authenticate.authentication.SessionBoundJWTAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
    ],
    "DEFAULT_PAGINATION_CLASS": "core.pagination.StandardPagination",
    "PAGE_SIZE": 20,
    "EXCEPTION_HANDLER": "core.exceptions.global_exception_handler",
    # MUST be an integer, never None. Left at DRF's default of None,
    # `SimpleRateThrottle.get_ident` falls through to using the whole
    # X-Forwarded-For header verbatim as the throttle identity — and that header
    # is supplied by the caller. An attacker varying it per request lands in a
    # fresh bucket every time, silently voiding LoginIPThrottle and
    # RefreshThrottle, the two limits standing in front of credential stuffing.
    # An integer makes DRF count in from the right instead, past the hops it
    # trusts, to an address the client cannot forge. See _NUM_PROXIES above.
    "NUM_PROXIES": _NUM_PROXIES,
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.AnonRateThrottle",
        "rest_framework.throttling.UserRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "anon": "100/hour",
        "user": "1000/hour",
        # authenticate app scoped throttles (per-IP for anon login/refresh bursts;
        # per-username handled by a dedicated scope on the login view).
        "auth_login_ip": "20/minute",
        "auth_login_user": "10/minute",
        "auth_refresh": "60/minute",
        # Global search: its own per-user bucket rather than the shared "user"
        # rate. One search is up to nine queries across seven apps and is driven
        # keystroke by keystroke, so without a scope of its own an undebounced
        # search box would spend the whole 1000/hour API budget and throttle the
        # user out of every other endpoint. See search/throttling.py.
        "search_query": "60/minute",
    },
}

SIMPLE_JWT = {
    # Short-lived access token; server-side revocation is enforced per-request by
    # authenticate.authentication.SessionBoundJWTAuthentication regardless of lifetime.
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=15),
    # Refresh is an opaque, server-stored AuthSession credential — NOT a SimpleJWT
    # refresh token. This lifetime is unused; AUTH_SESSION_* below govern refresh.
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
    "UPDATE_LAST_LOGIN": False,
    # Algorithm is pinned server-side (never trust an incoming token's alg header).
    "ALGORITHM": "HS256",
    "SIGNING_KEY": config("SECRET_KEY"),
    "ISSUER": config("JWT_ISSUER", default="grandway"),
    "AUDIENCE": config("JWT_AUDIENCE", default="grandway-api"),
    "AUTH_HEADER_TYPES": ("Bearer",),
    "AUTH_TOKEN_CLASSES": ("rest_framework_simplejwt.tokens.AccessToken",),
}

# ---------------------------------------------------------------------------
# authenticate app — session + refresh-cookie configuration.
# Access token is returned in the response body; the refresh credential is an
# opaque server-stored token (see authenticate.models.AuthSession).
# ---------------------------------------------------------------------------
AUTH_SESSION_IDLE_LIFETIME = timedelta(hours=config("AUTH_SESSION_IDLE_HOURS", default=12, cast=int))
AUTH_SESSION_ABSOLUTE_LIFETIME = timedelta(days=config("AUTH_SESSION_ABSOLUTE_DAYS", default=7, cast=int))
AUTH_MAX_ACTIVE_DEVICES = config("AUTH_MAX_ACTIVE_DEVICES", default=3, cast=int)

# How stale AuthSession.last_used_at may get before an authenticated request
# refreshes it. The column is shown to users on the "your active sessions"
# screen, so it has to mean what it says — but writing it on every request would
# add an UPDATE to the hot path of every authenticated call in the project. A
# coarse resolution buys the honesty for roughly one write per session per
# interval. Set to 0 to write on every request.
AUTH_SESSION_LAST_USED_RESOLUTION = timedelta(minutes=config("AUTH_SESSION_LAST_USED_MINUTES", default=5, cast=int))

# Refresh-cookie transport. Development returns the refresh token in the response
# body (cookie disabled); production overrides AUTH_REFRESH_COOKIE_ENABLED=True with
# Secure/HttpOnly/SameSite set. See core/settings/production.py.
AUTH_REFRESH_COOKIE_ENABLED = False
AUTH_REFRESH_COOKIE_NAME = "grandway_refresh"
AUTH_REFRESH_COOKIE_SECURE = True
AUTH_REFRESH_COOKIE_HTTPONLY = True
AUTH_REFRESH_COOKIE_SAMESITE = "Lax"
AUTH_REFRESH_COOKIE_PATH = "/api/v1/auth/"

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {
        "request_id": {
            "()": "core.logging.RequestIDFilter",
        },
    },
    "formatters": {
        "structured": {
            "()": "core.logging.StructuredFormatter",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "structured",
            "filters": ["request_id"],
        },
        "rotating_file": {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": str(LOG_DIR / "app.log"),
            "maxBytes": 10 * 1024 * 1024,
            "backupCount": 10,
            "formatter": "structured",
            "filters": ["request_id"],
            "encoding": "utf-8",
        },
    },
    "root": {
        "handlers": ["console", "rotating_file"],
        "level": "INFO",
    },
    "loggers": {
        "django": {
            "handlers": ["console", "rotating_file"],
            "level": "INFO",
            "propagate": False,
        },
        "core": {
            "handlers": ["console", "rotating_file"],
            "level": "DEBUG",
            "propagate": False,
        },
    },
}
