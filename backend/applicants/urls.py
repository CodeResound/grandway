"""URL routes for the applicants app (mounted at /api/v1/applicants/)."""

from django.urls import path

from applicants.views import (
    ApplicantDetailView,
    ApplicantHistoryView,
    ApplicantListCreateView,
    ApplicantStatusView,
)

app_name = "applicants"

urlpatterns = [
    path("", ApplicantListCreateView.as_view(), name="applicant-list"),
    path("<uuid:applicant_id>/", ApplicantDetailView.as_view(), name="applicant-detail"),
    path("<uuid:applicant_id>/status/", ApplicantStatusView.as_view(), name="applicant-status"),
    path("<uuid:applicant_id>/history/", ApplicantHistoryView.as_view(), name="applicant-history"),
]
