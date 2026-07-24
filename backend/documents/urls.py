"""URL routes for the documents app (mounted at /api/v1/documents/)."""

from django.urls import path

from documents.views import (
    DocumentArchiveView,
    DocumentDetailView,
    DocumentHistoryView,
    DocumentListCreateView,
    DocumentRestoreView,
    DocumentStatusView,
    WorkspaceListView,
)

app_name = "documents"

urlpatterns = [
    path("", DocumentListCreateView.as_view(), name="document-list"),
    # Declared before the ``<uuid:document_id>/`` routes so the literal segment
    # is never shadowed by the id pattern.
    path("workspaces/", WorkspaceListView.as_view(), name="workspace-list"),
    path("<uuid:document_id>/", DocumentDetailView.as_view(), name="document-detail"),
    path("<uuid:document_id>/status/", DocumentStatusView.as_view(), name="document-status"),
    path("<uuid:document_id>/archive/", DocumentArchiveView.as_view(), name="document-archive"),
    path("<uuid:document_id>/restore/", DocumentRestoreView.as_view(), name="document-restore"),
    path("<uuid:document_id>/history/", DocumentHistoryView.as_view(), name="document-history"),
]
