"""URL patterns for the dashboards app.

Eight read-only routes under ``/api/v1/dashboard/``. The prefix is singular
while the app is plural: there is one dashboard, assembled from eight sections,
and a client author reading the path should see the screen rather than the
Django app. The `permission_key` prefix stays `dashboards.*`, matching the app.
"""

from django.urls import path

from dashboards import views

app_name = "dashboards"

urlpatterns = [
    path("summary/", views.DashboardSummaryView.as_view(), name="dashboard-summary"),
    path("today/", views.DashboardTodayView.as_view(), name="dashboard-today"),
    path("pipeline/", views.DashboardPipelineView.as_view(), name="dashboard-pipeline"),
    path("blockers/", views.DashboardBlockersView.as_view(), name="dashboard-blockers"),
    path("workload/", views.DashboardWorkloadView.as_view(), name="dashboard-workload"),
    path("conversion/", views.DashboardConversionView.as_view(), name="dashboard-conversion"),
    path("outcomes/", views.DashboardOutcomesView.as_view(), name="dashboard-outcomes"),
    path("activity/", views.DashboardActivityView.as_view(), name="dashboard-activity"),
]
