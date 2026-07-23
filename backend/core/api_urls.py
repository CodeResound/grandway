from django.urls import include, path

app_name = "v1"

urlpatterns: list = [
    path("policy/", include("core.policy_engine.urls", namespace="policy")),
    path("auth/", include("authenticate.urls", namespace="auth")),
    path("audit/", include("audit.urls", namespace="audit")),
    path("leads/", include("leads.urls", namespace="leads")),
]
