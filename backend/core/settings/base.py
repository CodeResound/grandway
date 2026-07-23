from datetime import timedelta
from pathlib import Path

from decouple import Csv, config

BASE_DIR = Path(__file__).resolve().parent.parent.parent

LOG_DIR = BASE_DIR.parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

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
]

# The authenticate app owns the platform's identity layer with a custom user model.
AUTH_USER_MODEL = "authenticate.User"

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    # Must be early — before CommonMiddleware — so CORS headers reach every response.
    "corsheaders.middleware.CorsMiddleware",
    "core.middleware.RequestIDMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
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

# django-otp: TOTP MFA. The issuer label shown in authenticator apps. No
# OTPMiddleware is installed — the authenticate login service verifies TOTP codes
# directly and binds MFA state to the session it issues.
OTP_TOTP_ISSUER = config("OTP_TOTP_ISSUER", default="Grandway")

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

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
