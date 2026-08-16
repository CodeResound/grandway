"""URL patterns for the search app.

Two read-only routes under ``/api/v1/search/``. ``types/`` is declared before
the bare route so it is matched as a path rather than being mistaken for one;
the bare route takes no path argument, so the two cannot actually collide, but
the order is the one a reader expects and costs nothing to keep.
"""

from django.urls import path

from search import views

app_name = "search"

urlpatterns = [
    path("types/", views.SearchableTypesView.as_view(), name="search-types"),
    path("", views.GlobalSearchView.as_view(), name="search-query"),
]
