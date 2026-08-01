from django.apps import AppConfig


class SearchConfig(AppConfig):
    """The second app in the project that owns no table, after ``dashboards``.

    There is no ``models.py`` and no ``migrations/`` directory, deliberately:
    every row this app returns is produced at read time by the search selector
    of the app that owns it. Nothing is indexed here, copied here, or kept in
    step here — there is no index to rebuild and nothing that could go stale
    against the records it finds (``concepts/search.txt`` — "Constraints").
    """

    default_auto_field = "django.db.models.BigAutoField"
    name = "search"
    verbose_name = "Search"
