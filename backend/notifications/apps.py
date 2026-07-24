from django.apps import AppConfig


class NotificationsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "notifications"
    verbose_name = "Notifications"

    def ready(self) -> None:
        """Connect the five lifecycle-alert receivers (§11).

        Registered here rather than at module import time or in ``models.py``,
        so each receiver is connected exactly once and only after the app
        registry is populated — importing ``signals`` pulls in five other apps'
        models.
        """
        from notifications import signals  # noqa: F401  (import registers the receivers)
