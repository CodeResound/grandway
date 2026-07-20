from datetime import timedelta
from pathlib import Path

import decouple

# Point decouple at .env.development before base settings are loaded.
# This must happen before `from .base import *` so config() reads the right file.
_env_file = Path(__file__).resolve().parents[3] / ".env.development"
decouple.config = decouple.Config(decouple.RepositoryEnv(str(_env_file)))

from .base import *  # noqa: F401, F403, E402

DEBUG = True

# Dev-only: allow any origin so a local frontend on any port can call the API.
# Never set this alongside CORS_ALLOW_CREDENTIALS=True (django-cors-headers
# rejects that combination). Staging/production get no override here and so
# default to allowing zero cross-origin requests until explicitly configured.
CORS_ALLOW_ALL_ORIGINS = True

# In development, JWT tokens are returned in the response body (not HttpOnly cookie).
# Cookie-based auth for production is configured in the auth app when introduced.
SIMPLE_JWT = {
    **SIMPLE_JWT,  # noqa: F405
    "ACCESS_TOKEN_LIFETIME": timedelta(hours=24),
}

LOGGING["root"]["level"] = "DEBUG"  # noqa: F405
