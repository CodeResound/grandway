from django.apps import AppConfig


class DashboardsConfig(AppConfig):
    """The one app in the project that owns no table.

    There is no ``models.py`` and no ``migrations/`` directory, deliberately:
    every number this app returns is derived at read time from the domain apps,
    so there is nothing to migrate and nothing that could drift out of step with
    the records it summarizes.
    """

    default_auto_field = "django.db.models.BigAutoField"
    name = "dashboards"
    verbose_name = "Dashboards"
