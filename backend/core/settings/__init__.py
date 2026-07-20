import os

# Auto-select only when DJANGO_SETTINGS_MODULE points to this package itself,
# not to a specific settings file within it (e.g. core.settings.testing).
_target = os.environ.get("DJANGO_SETTINGS_MODULE", "")
if _target in ("core.settings", ""):
    _env = os.environ.get("ENVIRONMENT", "development")
    if _env == "production":
        from .production import *  # noqa: F401, F403
    elif _env == "staging":
        from .staging import *  # noqa: F401, F403
    else:
        from .development import *  # noqa: F401, F403
