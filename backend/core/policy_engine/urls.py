from django.urls import path

from core.policy_engine.views import (
    EndpointChangelogView,
    EndpointDependencyView,
    EndpointVersionListView,
    PolicyApplicationDetailView,
    PolicyApplicationListView,
    PolicyEndpointDetailView,
    UIPermissionTreeView,
)

app_name = "policy"

urlpatterns = [
    path("apps/", PolicyApplicationListView.as_view(), name="app-list"),
    path("apps/<str:app_key>/", PolicyApplicationDetailView.as_view(), name="app-detail"),
    path("permissions/tree/", UIPermissionTreeView.as_view(), name="permission-tree"),
    path("endpoints/<str:permission_key>/", PolicyEndpointDetailView.as_view(), name="endpoint-detail"),
    path(
        "endpoints/<str:permission_key>/dependencies/",
        EndpointDependencyView.as_view(),
        name="endpoint-dependencies",
    ),
    path(
        "endpoints/<str:permission_key>/versions/",
        EndpointVersionListView.as_view(),
        name="endpoint-versions",
    ),
    path(
        "endpoints/<str:permission_key>/changelog/",
        EndpointChangelogView.as_view(),
        name="endpoint-changelog",
    ),
]
