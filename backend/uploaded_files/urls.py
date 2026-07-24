"""URL routes for the uploaded_files app (mounted at /api/v1/files/).

A flat resource with four custom actions. ``files/`` rather than
``uploaded-files/`` because the mount point is what a client types on every
call, and the app name's qualifier ("uploaded") distinguishes it from nothing —
there is no other kind of file in this API.

The per-record file panels are this list filtered, not nested routes:
``GET /api/v1/files/?applicant=<id>`` rather than
``/api/v1/applicants/<id>/files/``. Nesting would put a files route inside five
other apps' URL namespaces and make the owning app appear to own file access,
which is the coupling this app exists to avoid.
"""

from django.urls import path

from uploaded_files.views import (
    FileArchiveView,
    FileDetailView,
    FileDownloadView,
    FileListUploadView,
    FileReplaceView,
    FileRestoreView,
    FileReviewView,
    FileVersionsView,
)

app_name = "uploaded_files"

urlpatterns = [
    path("", FileListUploadView.as_view(), name="file-list"),
    path("<uuid:file_id>/", FileDetailView.as_view(), name="file-detail"),
    path("<uuid:file_id>/download/", FileDownloadView.as_view(), name="file-download"),
    path("<uuid:file_id>/versions/", FileVersionsView.as_view(), name="file-versions"),
    path("<uuid:file_id>/replace/", FileReplaceView.as_view(), name="file-replace"),
    path("<uuid:file_id>/verify/", FileReviewView.as_view(), name="file-verify"),
    path("<uuid:file_id>/archive/", FileArchiveView.as_view(), name="file-archive"),
    path("<uuid:file_id>/restore/", FileRestoreView.as_view(), name="file-restore"),
]
