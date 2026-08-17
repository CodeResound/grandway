import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

# Auto-select only when DJANGO_SETTINGS_MODULE points to this package itself,
# not to a specific settings file within it (e.g. core.settings.testing).
_target = os.environ.get("DJANGO_SETTINGS_MODULE", "")
if _target in ("core.settings", ""):
    _env = os.environ.get("ENVIRONMENT")

    if not _env:
        # The process environment wins; the repo-root .env exists only so local
        # tooling (manage.py runserver) need not export ENVIRONMENT by hand.
        _root_env_file = Path(__file__).resolve().parents[3] / ".env"
        if _root_env_file.exists():
            import decouple

            _env = decouple.Config(decouple.RepositoryEnv(str(_root_env_file)))("ENVIRONMENT", default=None)

    # Fail closed: a process that never states its environment must not boot
    # with development settings (DEBUG=True) by silent default.
    if _env == "production":
        from .production import *  # noqa: F401, F403
    elif _env == "staging":
        from .staging import *  # noqa: F401, F403
    elif _env == "development":
        from .development import *  # noqa: F401, F403
    elif _env == "testing":
        from .testing import *  # noqa: F401, F403
    else:
        raise ImproperlyConfigured(
            f"ENVIRONMENT is unset or invalid (got {_env!r}). Set ENVIRONMENT to one of "
            "production/staging/development/testing in the process environment or "
            "the repo-root .env; settings no longer fall back to development."
        )
