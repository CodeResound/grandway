import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

# Auto-select only when DJANGO_SETTINGS_MODULE points to this package itself,
# not to a specific settings file within it (e.g. core.settings.testing).
_target = os.environ.get("DJANGO_SETTINGS_MODULE", "")
if _target in ("core.settings", ""):
    _env = os.environ.get("ENVIRONMENT")

    _repo_root = Path(__file__).resolve().parents[3]

    if not _env:
        # The process environment wins; the repo-root .env exists only so local
        # tooling (manage.py runserver) need not export ENVIRONMENT by hand.
        _root_env_file = _repo_root / ".env"
        if _root_env_file.exists():
            import decouple

            _env = decouple.Config(decouple.RepositoryEnv(str(_root_env_file)))("ENVIRONMENT", default=None)

            # A stray .env on a production host is the one way this selection
            # can fail OPEN rather than closed. ENVIRONMENT unset with no .env
            # raises below; ENVIRONMENT unset WITH a developer's .env silently
            # selects development — DEBUG=True, no HTTPS redirect, no HSTS,
            # stack traces to clients — with no error and no warning. The only
            # symptom is a working site with every protection off.
            #
            # The presence of .env.production is unambiguous evidence that this
            # host is meant to serve production, so a .env that says otherwise
            # is a misconfiguration, not a preference. Refuse rather than
            # quietly downgrade. (Found by the v1.0.0 production smoke boot,
            # 2026-08-19; documented in GUIDE.txt §3.)
            if _env in ("development", "testing") and (_repo_root / ".env.production").exists():
                raise ImproperlyConfigured(
                    f"Refusing to boot: ENVIRONMENT is unset, so the repo-root .env selected "
                    f"{_env!r} — but .env.production is also present, so this host is meant to "
                    "serve production. Booting would silently enable DEBUG and disable the "
                    "HTTPS redirect, HSTS, and secure cookies. Export ENVIRONMENT=production in "
                    "the process environment, and remove the stray .env (see GUIDE.txt §3)."
                )

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
