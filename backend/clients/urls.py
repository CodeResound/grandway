"""URL routes for the clients app (mounted at /api/v1/clients/)."""

from django.urls import path

from clients.views import (
    ClientDetailView,
    ClientHistoryView,
    ClientListCreateView,
    ClientRestoreView,
    ClientRetireView,
)

app_name = "clients"

urlpatterns = [
    path("", ClientListCreateView.as_view(), name="client-list"),
    path("<uuid:client_id>/", ClientDetailView.as_view(), name="client-detail"),
    path("<uuid:client_id>/retire/", ClientRetireView.as_view(), name="client-retire"),
    path("<uuid:client_id>/restore/", ClientRestoreView.as_view(), name="client-restore"),
    path("<uuid:client_id>/history/", ClientHistoryView.as_view(), name="client-history"),
]
