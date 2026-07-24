from django.apps import AppConfig


class ChecklistsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "checklists"
    verbose_name = "Checklists"

    def ready(self) -> None:
        """Connect the country-inheritance receiver (§11).

        Registered here rather than at module import time or in ``models.py``,
        so the receiver is connected exactly once and only after the app
        registry is populated — importing ``signals`` pulls in another app's
        model.
        """
        from checklists import signals  # noqa: F401  (import registers the receiver)
