from datetime import timedelta
from pathlib import Path

import decouple

# §10: development reads .env.development when the file exists. When it does not
# (a CI runner, a fresh clone before `cp deploy/env.development.example`), fall back
# to the OS environment only (RepositoryEmpty) — the same rule production.py and
# staging.py apply, so a missing file is a missing-variable error, not a crash at
# import. Must run before `from .base import *` so config() reads the right source.
_env_file = Path(__file__).resolve().parents[3] / ".env.development"
if _env_file.exists():
    decouple.config = decouple.Config(decouple.RepositoryEnv(str(_env_file)))
else:
    decouple.config = decouple.Config(decouple.RepositoryEmpty())

from .base import *  # noqa: F401, F403, E402

DEBUG = True

# Dev-only: allow the known frontend origins explicitly so browser requests
# work from the LAN IP used in local development as well as localhost.
CORS_ALLOW_ALL_ORIGINS = False
CORS_ALLOWED_ORIGINS = decouple.config(
    "CORS_ALLOWED_ORIGINS",
    default="http://localhost:3000,http://127.0.0.1:3000,http://192.168.110.58:3000",
    cast=decouple.Csv(),
)
CORS_ALLOW_CREDENTIALS = True
CSRF_TRUSTED_ORIGINS = decouple.config(
    "CSRF_TRUSTED_ORIGINS",
    default="http://localhost:3000,http://127.0.0.1:3000,http://192.168.110.58:3000",
    cast=decouple.Csv(),
)

# In development, JWT tokens are returned in the response body (not HttpOnly cookie).
# Cookie-based auth for production is configured in the auth app when introduced.
SIMPLE_JWT = {
    **SIMPLE_JWT,  # noqa: F405
    "ACCESS_TOKEN_LIFETIME": timedelta(hours=24),
}

LOGGING["root"]["level"] = "DEBUG"  # noqa: F405
