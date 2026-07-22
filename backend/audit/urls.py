"""URL routes for the audit app (mounted at /api/v1/audit/)."""

from django.urls import path

from audit.views import AuditEventDetailView, AuditEventListView

app_name = "audit"

urlpatterns = [
    path("events/", AuditEventListView.as_view(), name="event-list"),
    path("events/<uuid:event_id>/", AuditEventDetailView.as_view(), name="event-detail"),
]
