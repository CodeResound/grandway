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
]
