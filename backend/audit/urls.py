"""URL routes for the audit app (mounted at /api/v1/audit/)."""

from django.urls import path

from audit.views import AuditEventDetailView, AuditEventFacetsView, AuditEventListView

app_name = "audit"

urlpatterns = [
    path("events/", AuditEventListView.as_view(), name="event-list"),
    # Declared before the detail route: `facets` is not a UUID so the converter
    # would reject it anyway, but keeping the literal first makes the intent
    # readable rather than dependent on converter behaviour.
    path("events/facets/", AuditEventFacetsView.as_view(), name="event-facets"),
    path("events/<uuid:event_id>/", AuditEventDetailView.as_view(), name="event-detail"),
]
