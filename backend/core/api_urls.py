from django.urls import include, path

app_name = "v1"

urlpatterns: list = [
    path("policy/", include("core.policy_engine.urls", namespace="policy")),
    path("auth/", include("authenticate.urls", namespace="auth")),
    path("audit/", include("audit.urls", namespace="audit")),
    path("leads/", include("leads.urls", namespace="leads")),
    path("applicants/", include("applicants.urls", namespace="applicants")),
    path("journeys/", include("applicant_journeys.urls", namespace="journeys")),
    path("catalogue/", include("institutions.urls", namespace="catalogue")),
    path("offers/", include("offers.urls", namespace="offers")),
    path("clients/", include("clients.urls", namespace="clients")),
    path("documents/", include("documents.urls", namespace="documents")),
    path("document-history/", include("document_history.urls", namespace="document_history")),
    path("document-templates/", include("document_templates.urls", namespace="document_templates")),
    path("files/", include("uploaded_files.urls", namespace="files")),
    path("checklists/", include("checklists.urls", namespace="checklists")),
    path("dashboard/", include("dashboards.urls", namespace="dashboards")),
]
