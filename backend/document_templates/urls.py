"""URL routes for the document_templates app (mounted at /api/v1/document-templates/).

Two literal segments, ``signatories/`` and ``templates/``, each with its own id
routes. The frontend's proposed path for the picker is a bare
``GET /signatures?active=true``; ours is
``/api/v1/document-templates/signatories/?status=active``. Its own contract says
endpoint paths are proposed while request/response bodies are what the UI
depends on, so project convention wins here — the mapping is spelled out in
``docs/INTEGRATION.md`` §7 so a client author is not left to guess it.
"""

from django.urls import path

from document_templates.views import (
    SignatoryDetailView,
    SignatoryListCreateView,
    SignatorySignatureView,
    SignatoryStatusView,
    TemplateDetailView,
    TemplateListCreateView,
    TemplateStatusView,
)

app_name = "document_templates"

urlpatterns = [
    path("signatories/", SignatoryListCreateView.as_view(), name="signatory-list"),
    path("signatories/<uuid:signatory_id>/", SignatoryDetailView.as_view(), name="signatory-detail"),
    path(
        "signatories/<uuid:signatory_id>/signature/",
        SignatorySignatureView.as_view(),
        name="signatory-signature",
    ),
    path("signatories/<uuid:signatory_id>/status/", SignatoryStatusView.as_view(), name="signatory-status"),
    path("templates/", TemplateListCreateView.as_view(), name="template-list"),
    path("templates/<uuid:template_id>/", TemplateDetailView.as_view(), name="template-detail"),
    path("templates/<uuid:template_id>/status/", TemplateStatusView.as_view(), name="template-status"),
]
