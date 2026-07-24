"""URL routes for the document_history app (mounted at /api/v1/document-history/).

The base path is ``document-history/``, not a nested route under
``documents/``. The two apps own separate resources, and nesting would have put
this app's routes inside another app's ``urls.py`` — and would have collided
with ``documents``' own ``/documents/<id>/history/``, which lists *audit events*
for a document and is a different thing entirely.
"""

from django.urls import path

from document_history.views import (
    SnapshotDetailView,
    SnapshotListCreateView,
    SnapshotRecoverView,
    SnapshotReprintView,
    TimelineView,
)

app_name = "document_history"

urlpatterns = [
    # Document-scoped: the version chain and the print timeline.
    path(
        "documents/<uuid:document_id>/snapshots/",
        SnapshotListCreateView.as_view(),
        name="snapshot-list",
    ),
    path(
        "documents/<uuid:document_id>/timeline/",
        TimelineView.as_view(),
        name="timeline",
    ),
    # Snapshot-scoped: one frozen record and the actions against it.
    path("snapshots/<uuid:snapshot_id>/", SnapshotDetailView.as_view(), name="snapshot-detail"),
    path("snapshots/<uuid:snapshot_id>/reprint/", SnapshotReprintView.as_view(), name="snapshot-reprint"),
    path("snapshots/<uuid:snapshot_id>/recover/", SnapshotRecoverView.as_view(), name="snapshot-recover"),
]
