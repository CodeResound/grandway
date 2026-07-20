from django.urls import include, path

app_name = "v1"

urlpatterns: list = [
    path("policy/", include("core.policy_engine.urls", namespace="policy")),
    # Add each new app's urls here under a versioned prefix, e.g.
    # path("auth/", include("authenticate.urls", namespace="auth")),
]
